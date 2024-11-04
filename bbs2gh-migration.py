#!/usr/bin/env python3.9
##
# Wrapper script to do the BB repo migration to GitHub using GitHub extension
##

import requests
import base64
import yaml
from ruamel.yaml import YAML
import subprocess
import csv
import ast
import os
import sys
import logging
from datetime import datetime
import paramiko
from scp import SCPClient
import urllib3
from requests.packages.urllib3.exceptions import InsecureRequestWarning
import time
import re
import argparse


##
# Setting values to do post tasks with GitHub API
##
roles = ["Viewers", "Contributors", "Managers"]
ad_groups_format = "GITHUB-<project_code>-<role>"
gh_team_format = "Project-<project_code>-<role>"
token = os.getenv('GH_PAT')
headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

prucore_rest_url = "https://core.pru.intranet.asia/rest/projects/"
prucore_url = "https://core.pru.intranet.asia/org/projects/"

def get_ad_group_name(project_code, role):
    return ad_groups_format.replace('<project_code>', project_code.upper()).replace('<role>', role)

def get_gh_team_name(project_code, role):
    return gh_team_format.replace('<project_code>', project_code.upper()).replace('<role>', role)

##
# Configure logging
##
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

def log_info(message):
    """ Log information message """
    logging.info(message)

def log_error(message):
    """ Log error message """
    logging.error(message)

def process_input(BB_PROJECT_KEY, BB_REPO_NAME, PROJECT_CODE, GH_ORG_NAME, PIPELINE_TYPE, USER_DEFINED_NAME):
    """ Process the input values """
    log_info(f"BB_PROJECT_KEY: {BB_PROJECT_KEY}")
    log_info(f"BB_REPO_NAME: {BB_REPO_NAME}")
    log_info(f"PROJECT_CODE: {PROJECT_CODE}")
    log_info(f"GH_ORG_NAME: {GH_ORG_NAME}")
    log_info(f"PIPELINE_TYPE: {PIPELINE_TYPE}")
    log_info(f"USER_DEFINED_NAME: {USER_DEFINED_NAME}")

    # Update the BB repository name to replace spaces with hyphens
    BB_REPO_NAME = BB_REPO_NAME.replace(" ", "-").lower()
    log_info(f"BB_REPO_NAME: {BB_REPO_NAME}")

    run_migration(BB_PROJECT_KEY, BB_REPO_NAME, PROJECT_CODE, GH_ORG_NAME, PIPELINE_TYPE, USER_DEFINED_NAME)

def valid_team_slug(org_login, team_slug):
    url = f"https://api.github.com/orgs/{org_login}/teams/{team_slug}"
    response = requests.get(url, headers=headers)
    return response.status_code == 200

def validate(project_code, org_login):
    """ Validate the project code """
    api_url = f"https://core.pru.intranet.asia/rest/projects/?code={project_code}"
    # Disabling cert verification warning
    urllib3.disable_warnings(InsecureRequestWarning)
    response = requests.get(api_url, verify=False)
    if response.status_code == 200 and response.json()['count'] > 0:
        log_info(f"Project code {project_code} is valid.")
    else:
        log_error(f"Project code {project_code} is invalid. Please onboard to https://core.pru.intranet.asia/org/projects/")
        sys.exit()
    # validate required teams exists in the org
    for role in roles:
        team_slug = get_gh_team_name(project_code, role)
        if not valid_team_slug(org_login, team_slug):
            log_error(f"Team '{team_slug}' does not exist in the organization '{org_login}'.")
            log_error(f"Please update the prucore project {project_code} to include this organisation '{org_login}'")
            sys.exit(1)

def get_new_repo_name(GH_ORG_NAME, BB_REPO_NAME, PROJECT_CODE, USER_DEFINED_NAME):
    """ Define the new GitHub repo name """
    # Define the new reponame prefix
    repo_name_prefix = f"{GH_ORG_NAME}-{PROJECT_CODE}-"
    repo_name_prefix = repo_name_prefix.replace("pru-", "")
    
    # Replace spaces with hyphens in the Bitbucket repo name
    no_space_BB_REPO_NAME = BB_REPO_NAME.replace(" ", "-")
    
    # Define the new GitHub repo name
    # Ex: <GH_ORG_NAME>-<PROJECT_CODE>-<BB_REPO_NAME>
    #     pss-ux2-ghmigrationrepo
    if USER_DEFINED_NAME != "None":
        no_space_BB_REPO_NAME = USER_DEFINED_NAME.replace(" ", "-")
    GH_REPO_NAME = repo_name_prefix + no_space_BB_REPO_NAME
    # Convert the repo name to lowercase    
    GH_REPO_NAME = GH_REPO_NAME.lower()    
    log_info(f"New GitHub repo name is {GH_REPO_NAME}")
    return GH_REPO_NAME

def set_migration_prequisite():
    """ Set the prequisite for the migration """
    # List of required environment variable names
    required_env_vars = ['BBS_USERNAME', 'BBS_PASSWORD', 'GH_PAT', 'AZURE_STORAGE_CONNECTION_STRING', 'BB_SERVER', 'BB_SSH_USERNAME']

    # Loop through each required environment variable
    for var_name in required_env_vars:
        # Attempt to retrieve the environment variable
        var_value = os.getenv(var_name)
        
        # Check if the environment variable is not set
        if var_value is None:
            # Raise an error specifying which environment variable is missing
            log_error(f"Environment variable '{var_name}' is not set.")
            raise ValueError()

    BBS_USERNAME = os.environ.get('BBS_USERNAME')
    BBS_PASSWORD = os.environ.get('BBS_PASSWORD')
    AZURE_STORAGE_CONNECTION_STRING = os.environ.get('AZURE_STORAGE_CONNECTION_STRING')

def run_export_archive(BB_PROJECT_KEY, BB_REPO_NAME, PROJECT_CODE, GH_ORG_NAME):
    """ Run the export archive """
    # Export the archive
    # BB_SERVER_URL="https://code-uat.pru.intranet.asia:8443"
    # BB_SERVER_URL="https://code.pruconnect.net"
    BB_SERVER_URL="https://code-new.pru.intranet.asia:8443/"
    log_info(f"Running the export command for {BB_PROJECT_KEY}/{BB_REPO_NAME}...")

    command = f"gh bbs2gh migrate-repo --bbs-server-url {BB_SERVER_URL} --bbs-project {BB_PROJECT_KEY} --bbs-repo {BB_REPO_NAME}"
    process = subprocess.Popen(command, universal_newlines=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    
    # Execute the command
    try:
        while True:
            output = process.stdout.readline()
            if output == '' and process.poll() is not None:
                break
            if output:
                print(output.strip())
                if "Export completed" in output:
                    pattern = r"BITBUCKET_SHARED_HOME(\S+)"
                    result_match = re.search(pattern, output)
                    if result_match:
                        archive_file_path = result_match.group(1)
                        print(archive_file_path)
        process.wait()
        err = process.stderr.read()
        if err:
            log_error(f"Export command failed, Please see the *.log in current folder for more details.")
            print(f"{err}")
            sys.exit()

        if 'archive_file_path' in locals():
            return archive_file_path

    except Exception as e:
        log_error(f"An error occurred: {e}")
        sys.exit()
    finally:
        process.stdout.close()
        process.stderr.close()

## 
# Download the exported archive from the Bitbucket server
##

def run_command(command):

    try:
        result = subprocess.run(command, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        log_info(f"Command '{command}' executed successfully.")
        print(result.stdout.decode('utf-8'))
    except subprocess.CalledProcessError as e:
        log_error(f"Command '{command}' failed with error code {e.returncode}.")
        print(e.stderr.decode('utf-8'))
        raise


def scp_command(EXPORT_ARCHIVE_FILE_PATH):
    """ Download the exported archive from the Bitbucket server """
    REMOTE_FILE_PATH = f"/apps/bitbucket/bitbucket/shared{EXPORT_ARCHIVE_FILE_PATH}"
    LOCAL_ARCHIVE_FILE_PATH=EXPORT_ARCHIVE_FILE_PATH.split("/")[-1]
    BB_SERVER = os.environ.get('BB_SERVER')
    BB_SSH_USERNAME = os.environ.get('BB_SSH_USERNAME')
    BB_TMP_LOCATION = "/mnt/bbmigration"

    run_command(f"ssh -o StrictHostKeyChecking=no -i ~/.ssh/id_rsa {BB_SSH_USERNAME}@{BB_SERVER} \"dzdo cat {REMOTE_FILE_PATH} > {BB_TMP_LOCATION}/{LOCAL_ARCHIVE_FILE_PATH}\"")
    run_command(f"scp -o StrictHostKeyChecking=no -i ~/.ssh/id_rsa {BB_SSH_USERNAME}@{BB_SERVER}:{BB_TMP_LOCATION}/{LOCAL_ARCHIVE_FILE_PATH} .")
    run_command(f"ssh -o StrictHostKeyChecking=no -i ~/.ssh/id_rsa {BB_SSH_USERNAME}@{BB_SERVER} \"rm {BB_TMP_LOCATION}/{LOCAL_ARCHIVE_FILE_PATH}\"")

def run_import_archive(BB_PROJECT_KEY, BB_REPO_NAME, PROJECT_CODE, GH_ORG_NAME, EXPORT_ARCHIVE_FILE_PATH, GH_NEW_REPO_NAME):
    """ Run the import archive command """
    #GH_NEW_REPO_NAME=get_new_repo_name(GH_ORG_NAME, BB_REPO_NAME, PROJECT_CODE, USER_DEFINED_NAME)
    LOCAL_ARCHIVE_FILE_PATH=EXPORT_ARCHIVE_FILE_PATH.split("/")[-1]
    # Import the archive to GitHub new repo
    BB_SERVER_URL="https://code.pruconnect.net"
    log_info(f"Migrating the repo {BB_PROJECT_KEY}/{BB_REPO_NAME} to {GH_ORG_NAME}/{GH_NEW_REPO_NAME}...")
    
    command = f"gh bbs2gh migrate-repo --archive-path {LOCAL_ARCHIVE_FILE_PATH} --github-org {GH_ORG_NAME} --github-repo {GH_NEW_REPO_NAME} --bbs-server-url {BB_SERVER_URL} --bbs-project {BB_PROJECT_KEY} --bbs-repo {BB_REPO_NAME}"
    process = subprocess.Popen(command, universal_newlines=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)

    # Execute the command
    try:
        while True:
            output = process.stdout.readline()
            if output == '' and process.poll() is not None:
                break
            if output:
                print(output.strip())
        process.wait()
        err = process.stderr.read()
        if err:
            print(f"{err}")
            log_error(f"Import command failed, Please see the *.log in current folder for more details.")
            sys.exit()
    except Exception as e:
        log_error(f"An error occurred: {e}")
        sys.exit()
    finally:
        process.stdout.close()
        process.stderr.close()

def run_migration(BB_PROJECT_KEY, BB_REPO_NAME, PROJECT_CODE, GH_ORG_NAME, PIPELINE_TYPE, USER_DEFINED_NAME):
    """ Run the migration steps with export and import """
    # Set the migration prequisite
    set_migration_prequisite()
    # Validate the project code
    validate(PROJECT_CODE, GH_ORG_NAME)
    GH_NEW_REPO_NAME=get_new_repo_name(GH_ORG_NAME, BB_REPO_NAME, PROJECT_CODE, USER_DEFINED_NAME)
    # Run the export archive
    EXPORT_ARCHIVE_FILE_PATH=run_export_archive(BB_PROJECT_KEY, BB_REPO_NAME, PROJECT_CODE, GH_ORG_NAME)
    # Download the archive file
    # EXPORT_ARCHIVE_FILE_PATH="./Bitbucket_export_19.tar"
    scp_command(EXPORT_ARCHIVE_FILE_PATH)
    # Add the repo name to the exclusion org rulesets
    repo_name_to_exclusion_ruleset(GH_ORG_NAME, GH_NEW_REPO_NAME, "add")
    # Import the archive file
    run_import_archive(BB_PROJECT_KEY, BB_REPO_NAME, PROJECT_CODE, GH_ORG_NAME, EXPORT_ARCHIVE_FILE_PATH, GH_NEW_REPO_NAME)
    # Sleep for 15 seconds to get the repo get unlocked after import
    time.sleep(15)
    # Post migration tasks
    update_org_repository(GH_ORG_NAME, GH_NEW_REPO_NAME, PROJECT_CODE)
    create_status_file_in_repo(GH_ORG_NAME, GH_NEW_REPO_NAME, BB_PROJECT_KEY, BB_REPO_NAME)
    # Update repository custom properties
    update_repo_properties(GH_ORG_NAME, GH_NEW_REPO_NAME)
    update_org_repository_topics(GH_ORG_NAME, GH_NEW_REPO_NAME, PROJECT_CODE)
    update_org_repository_access(GH_ORG_NAME, GH_NEW_REPO_NAME, PROJECT_CODE)
    # Create CODEOWNERS file in destination repo
    create_codeowners_in_repo(GH_ORG_NAME, GH_NEW_REPO_NAME, BB_PROJECT_KEY, BB_REPO_NAME, PROJECT_CODE)
    update_or_create_enviroments(GH_ORG_NAME, GH_NEW_REPO_NAME, PROJECT_CODE)
    # Update webhook for the repository
    if PIPELINE_TYPE == "Platform_Jenkins" or PIPELINE_TYPE == "Old_Jenkins":
      update_repository_webhook(GH_ORG_NAME, GH_NEW_REPO_NAME, BB_PROJECT_KEY, BB_REPO_NAME, PIPELINE_TYPE)
    elif PIPELINE_TYPE == "Both_Jenkins":
      update_repository_webhook(GH_ORG_NAME, GH_NEW_REPO_NAME, BB_PROJECT_KEY, BB_REPO_NAME, "Platform_Jenkins")
      update_repository_webhook(GH_ORG_NAME, GH_NEW_REPO_NAME, BB_PROJECT_KEY, BB_REPO_NAME, "Old_Jenkins")
    # Add the repo to the migration tracker
    update_migration_tracker(GH_ORG_NAME, GH_NEW_REPO_NAME, BB_PROJECT_KEY, BB_REPO_NAME)
    remove_repo_admin(GH_ORG_NAME, GH_NEW_REPO_NAME)
    # Remove the repo name to the exclusion org rulesets
    repo_name_to_exclusion_ruleset(GH_ORG_NAME, GH_NEW_REPO_NAME, "remove")    
    
##
# Post migration tasks
## 

def update_org_repository(org_login, repo_slug, project_code):
    url = f"https://api.github.com/repos/{org_login}/{repo_slug}"

    project_url = prucore_url + project_code
    project_name = get_project_details(project_code).get('name', None)

    data = {
        "name": repo_slug,
        "description": f"Code repository for application '{repo_slug.split('-')[-1]}' under project '{project_name}'",
        "homepage": project_url,
        "private": "private",
        #"visibility": "private" if repo_data.get('private', True) else "internal",  # Options: "public", "private", "internal"
        "visibility": "private",
        "has_issues": False, # we use jira
        "has_projects": False, # we use jira
        "has_wiki": False, # we use confluence
        "has_downloads": False, # we use artifactory
        "is_template": False, # we use template repository
        "auto_init": False, # we use template repository
        "delete_branch_on_merge": True, # Options: "true", "false"
        "allow_squash_merge": True, # Options: "true", "false"
        "allow_merge_commit": True, # Options: "true", "false"
        "allow_rebase_merge": False, # Options: "true", "false"
        "allow_auto_merge": True, # Options: "true", "false"
    }

    response = requests.patch(url, headers=headers, json=data)
    if response.status_code in [200, 201]:
        result_data = response.json()
        log_info(f"Repository '{repo_slug}' created successfully with ID: {result_data['id']}")
    else:
        log_error(f"Failed to update repository. Status code: {response.status_code}")
        log_error(response.text)
        sys.exit(1)
    return response.status_code == 201

def create_status_file_in_repo(GH_ORG_NAME, GH_NEW_REPO_NAME, BB_PROJECT_KEY, BB_REPO_NAME):
    #
    file_name = "migration_status.txt"
    # Get the current date and time
    current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Content to write in the file
    file_content = f"Migrated on: {current_date}\nMigrated from: {BB_PROJECT_KEY}/{BB_REPO_NAME}"

    # GitHub API URL
    api_url = f"https://api.github.com/repos/{GH_ORG_NAME}/{GH_NEW_REPO_NAME}/contents/{file_name}"
    
    # Encode file content to base64
    base64_content = base64.b64encode(file_content.encode()).decode()

    # Request body
    payload = {
        "message": "Add file via migrator",
        "content": base64_content
    }

    # Make PUT request to create file
    response = requests.put(api_url, headers=headers, json=payload)

    # Check if request was successful
    if response.status_code == 201:
        log_info(f"{file_name} file created successfully.")
    else:
        log_info(f"Failed to create file {file_name}.")
        log_error(response.text)

def create_codeowners_in_repo(GH_ORG_NAME, GH_NEW_REPO_NAME, BB_PROJECT_KEY, BB_REPO_NAME, PROJECT_CODE):
    #
    file_name = "CODEOWNERS"

    # Content to write in the file
    group_name_prefix = GH_ORG_NAME.replace("pru-", "")
    file_content = f"* @{GH_ORG_NAME}/Project-{PROJECT_CODE}-Managers"

    # GitHub API URL
    api_url = f"https://api.github.com/repos/{GH_ORG_NAME}/{GH_NEW_REPO_NAME}/contents/{file_name}"
    
    # Encode file content to base64
    base64_content = base64.b64encode(file_content.encode()).decode()

    # Request body
    payload = {
        "message": "Add file via migrator",
        "content": base64_content
    }

    # Make PUT request to create file
    response = requests.put(api_url, headers=headers, json=payload)

    # Check if request was successful
    if response.status_code == 201:
        log_info(f"{file_name} file created successfully.")
    else:
        log_info(f"Failed to create file {file_name}.")
        log_error(response.text)

def update_repo_properties(GH_ORG_NAME, GH_NEW_REPO_NAME):
    """ Update repository custom properties """
    properties = [
        {"property_name":"default_branch","value":"main"},
        {"property_name":"deployment_type","value":"others"},
        {"property_name":"pipeline_type","value":"Jenkins"},
        {"property_name":"production_workflow","value":"null"},
    ]

    # GitHub API URL
    api_url = f"https://api.github.com/repos/{GH_ORG_NAME}/{GH_NEW_REPO_NAME}/properties/values"

    # Request body
    payload = {
        "properties":properties
    }

    # Make PUT request to create file
    response = requests.patch(api_url, headers=headers, json=payload)

    # Check if request was successful
    if response.status_code == 200 or response.status_code == 201 or response.status_code == 204:
        log_info(f"repository custom properties updated")
    else:
        log_info(f"Failed to update repository custom properties")
        log_error(response.text)

def update_or_create_enviroments(GH_ORG_NAME, GH_NEW_REPO_NAME, PROJECT_CODE):
    #environments = repo_data.get('environments', [])
    #if "production" not in environments:
    environments = []
    environments.append('production')

    # get team id from team slug
    team_slug = get_gh_team_name(PROJECT_CODE.upper(), "Managers")
    url = f"https://api.github.com/orgs/{GH_ORG_NAME}/teams/{team_slug}"
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        team_id = response.json().get('id', None)
    else:
        log_error(f"Failed to get team id for '{team_slug}'. Status code: {response.status_code}")
        log_error(response.text)
        #sys.exit(1)

    for env in environments:
        url = f"https://api.github.com/repos/{GH_ORG_NAME}/{GH_NEW_REPO_NAME}/environments/{env}"
        if env == "production":
            data = {
                "prevent_self_review": True,
                "reviewers" : [
                    {
                        "type": "Team",
                        "id": team_id
                    },
                ],
                "deployment_branch_policy" : {
                    "protected_branches" : False,
                    "custom_branch_policies" : True,
                }
            }
        else:
            # no reviewers for non-prd environment
            data = {
                "reviewers": [],
                "deployment_branch_policy": {
                    "protected_branches": False,
                    "custom_branch_policies": True
                }
            }
        response = requests.put(url, headers=headers, json=data)
        if response.status_code == 200:
            log_info(f"Environment '{env}' added to the repository '{GH_NEW_REPO_NAME}' successfully.")
        else:
            log_error(f"Failed to add environment '{env}' to the repository '{GH_NEW_REPO_NAME}'. Status code: {response.status_code}")
            log_error(response.text)
            #sys.exit(1)

        # add deployment brach policy for 'production' environment to allow only main and master branches
        if env == 'production':
            branches = ['main', 'master']
            for branch in branches:
                url = f"https://api.github.com/repos/{GH_ORG_NAME}/{GH_NEW_REPO_NAME}/environments/{env}/deployment-branch-policies"
                data = {
                    "name": branch,
                    "type": "branch"
                }
                response = requests.post(url, headers=headers, json=data)
                if response.status_code == 200:
                    log_info(f"Deployment branch policy added to the repository '{GH_NEW_REPO_NAME}' successfully for the environment '{env}'.")
                else:
                    log_error(f"Failed to add deployment branch policy to the repository '{GH_NEW_REPO_NAME}'. Status code: {response.status_code}")
                    log_error(response.text)
                    #sys.exit(1)

def update_org_repository_topics(GH_ORG_NAME, GH_NEW_REPO_NAME, PROJECT_CODE):
    #topics = repo_data.get('topics', [])
    # project_code is the first topic and repo name is the second topic
    topics = [PROJECT_CODE.lower()]
    url = f"https://api.github.com/repos/{GH_ORG_NAME}/{GH_NEW_REPO_NAME}/topics"
    data = {
        "names": topics
    }
    # print(topics)
    # print(data)
    response = requests.put(url, headers=headers, json=data)
    if response.status_code == 200:
        log_info(f"Topics '{topics}' added to the repository '{GH_NEW_REPO_NAME}' successfully.")
    else:
        log_error(f"Failed to add topics '{topics}' to the repository '{GH_NEW_REPO_NAME}'. Status code: {response.status_code}")
        log_error(response.text)
        #sys.exit(1)

def update_org_repository_access(GH_ORG_NAME, GH_NEW_REPO_NAME, PROJECT_CODE):
    # add teams to the repository
    for role in roles:
        team_slug = get_gh_team_name(PROJECT_CODE.upper(), role)
        url = f"https://api.github.com/orgs/{GH_ORG_NAME}/teams/{team_slug}/repos/{GH_ORG_NAME}/{GH_NEW_REPO_NAME}"
        if role == 'Viewers':
            permission = 'pull'
        elif role == 'Contributors':
            permission = 'push'
        elif role == 'Managers':
            permission = 'managers'
        else:
            permission = 'pull'
        data = {
            "permission": permission
        }
        response = requests.put(url, headers=headers, json=data)
        if response.status_code == 204:
            log_info(f"Team '{team_slug}' added to the repository '{GH_NEW_REPO_NAME}' successfully with '{permission}' permission.")
        else:
            log_error(f"Failed to add team '{team_slug}' to the repository '{GH_NEW_REPO_NAME}'. Status code: {response.status_code}")
            log_error(response.text)
            sys.exit(1)

def update_team_membership(add, org_name, team_slug, member):
    url  = f"https://api.github.com/orgs/{org_name}/teams/{team_slug}/memberships/{member}"
    if add:
        response = requests.put(url, headers=headers)
        if response.status_code == 200:
            log_info(f"Member '{member}' added to the team '{team_slug}' successfully.")
        else:
            log_error(f"Failed to add member '{member}' to the team. Status code: {response.status_code}")
            log_error(response.text)
    else:
        response = requests.delete(url, headers=headers)
        if response.status_code == 204:
            log_info(f"Member '{member}' removed from the team '{team_slug}' successfully.")
        else:
            log_error(f"Failed to remove member '{member}' from the team. Status code: {response.status_code}")
            log_error(response.text)

def get_project_details(prj_code):
    url = prucore_rest_url + f"?code={prj_code}"
    response = requests.get(url, verify=False)
    if response.status_code == 200:
        response_data = response.json()
        if response_data.get('count', 0) > 0:
            return response_data.get('results', [])[0]
    return None

def create_github_team(org_name, team_name):
    url = f"https://api.github.com/orgs/{org_name}/teams"
    data = {
        "name": team_name,
        "description": f"{team_name.split('-')[-1]} team for project {get_project_details(team_name.split('-')[-2]).get('name', '')}",
        "privacy": "closed"  # Options: "secret", "closed"
    }
    # Send the REST request to create a team
    response = requests.post(url, headers=headers, json=data)
    if response.status_code == 201:
        team_data = response.json()
        team_id = team_data["id"]
        log_info(f"Team '{team_name}' created successfully with ID: {team_id}")
        update_team_membership(False, org_name, team_name, "SRVPSSAPRCISTOOLS02_pru")
    elif response.status_code == 422:
        log_info(f"Team '{team_name}' already exists.")
    else:
        log_error(f"Failed to create team. Status code: {response.status_code}")
        log_error(response.text)
        #sys.exit(1)
    return response.status_code == 201

def update_team_parent(org_login, child_team, parent_team):
    # get thd id for parent team
    url = f"https://api.github.com/orgs/{org_login}/teams/{parent_team}"
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
         parent_team_id = response.json().get('id', None)
    else:
        log_error(f"Failed to get team id for '{parent_team}'. Status code: {response.status_code}")
        log_error(response.text)
        sys.exit(1)
    # update the parent team for the child team
    url = f"https://api.github.com/orgs/{org_login}/teams/{child_team}"
    data = {
        "parent_team_id": parent_team_id
    }
    response = requests.patch(url, headers=headers, json=data)
    if response.status_code == 200:
        log_info(f"Team '{child_team}' is now a child of team '{parent_team}' successfully.")
    else:
        log_error(f"Failed to update team '{child_team}' as a child of team '{parent_team}'. Status code: {response.status_code}")
        log_error(response.text)
        #sys.exit(1)

def update_ruleset(org_code, existing_ruleset_id, conditions):
    """Updating the ruleset with the new conditions"""
    log_info(f"Updating ruleset {existing_ruleset_id}")
    api_url = f"https://api.github.com/orgs/{org_code}/rulesets/{existing_ruleset_id}" 

    response = requests.put(f"{api_url}", headers=headers, json={
        "conditions": conditions
    })

    # Debug
    log_info(conditions)

    if response.status_code not in [200, 201]:
        error_message = response.json().get('message')
        log_error(f"Failed to update ruleset for {existing_ruleset_id}. Status code: {response.status_code}, Message: {error_message}")
        sys.exit(1)

def repo_name_to_exclusion_ruleset(org_code, repo_name, action):
    """Add or remove the repository_name to the exclude list in the ruleset"""
    # Get existing rulesets
    api_url = f"https://api.github.com/orgs/{org_code}/rulesets"
    response = requests.get(f"{api_url}", headers=headers)
    if response.status_code not in [200, 201]:
        error_message = response.json().get('message')
        log_error(f"Failed to get ruleset for {org_code}. Status code: {response.status_code}, Message: {error_message}")
        sys.exit(1)
    existing_rulesets = response.json()

    # Loop through each ruleset and get the conditions
    for ruleset in existing_rulesets:
        ruleset_name = ruleset['name']
        # Check for the ruleset which are managed by GT
        if ruleset_name in ['branch_names', 'main_and_master', 'other_protected_branch ', 'restrict_binary_file_upload']:  
            #log_info(ruleset_name)
            existing_ruleset_id = next((r['id'] for r in existing_rulesets if r['name'] == ruleset_name), None)
            response = requests.get(f"{api_url}/{existing_ruleset_id}", headers=headers)
        
            # Get the existing rulesets conditions
            if response.status_code not in [200, 201]:
                error_message = response.json().get('message')
                log_error(f"Failed to get ruleset for {org_code}. Status code: {response.status_code}, Message: {error_message}")
                sys.exit(1)
            existing_ruleset_condition = response.json()["conditions"]

            # Based on the action, add or remove the repo_name to the exclude list 
            if action == "add" and "repository_name" in existing_ruleset_condition:
                existing_ruleset_condition['repository_name']['exclude'].append(repo_name)
                update_ruleset(org_code, existing_ruleset_id, existing_ruleset_condition)
            elif action == "remove" and "repository_name" in  existing_ruleset_condition:
                # Debug
                log_info("removing reponame from the exclude list..")
                log_info(existing_ruleset_condition)
                log_info(repo_name)
                existing_ruleset_condition['repository_name']['exclude'].remove(repo_name)
                # When no exclude reponame is present, add ~ALL to include all repositories
                if not existing_ruleset_condition['repository_name']['exclude'] and not existing_ruleset_condition['repository_name']['include']:
                    existing_ruleset_condition['repository_name']['include'].append("~ALL")
                update_ruleset(org_code, existing_ruleset_id, existing_ruleset_condition)
            else:
                log_error("Invalid action or repository_name condition not found in the ruleset.")
                #sys.exit(1)
                
def update_migration_tracker(GH_ORG_NAME, GH_NEW_REPO_NAME, BB_PROJECT_KEY, BB_REPO_NAME):
    #
    file_name = "migration_tracker.txt"

    # GitHub API URL
    api_url = f"https://api.github.com/repos/pru-pss/pss-eta-bb2gh_migration/contents/{file_name}"

    # Get the current content of the file
    response = requests.get(api_url, headers=headers)
    if response.status_code == 200:
        file_info = response.json()
        sha = file_info['sha']
        content = base64.b64decode(file_info['content']).decode('utf-8')
    else:
        log_error(f"Failed to get file {file_name}.")
        log_error(response.text)

    # Get the current date
    current_date = datetime.now()
    DATE = current_date.strftime('%Y-%m-%d')

    # Content to add
    additional_content = f"{DATE},{BB_PROJECT_KEY},{BB_REPO_NAME},{GH_ORG_NAME},{GH_NEW_REPO_NAME}\n"

    # Update the content
    updated_content = content + additional_content
    updated_content_base64 = base64.b64encode(updated_content.encode('utf-8')).decode('utf-8')

    # Prepare the data for the update
    payload = {
        'message': 'Update file via migrator',
        'content': updated_content_base64,
        'sha': sha,
        'branch': 'main'
    }

    # Make PUT request to create file
    response = requests.put(api_url, headers=headers, json=payload)

    # Check if request was successful
    if response.status_code == 200:
        log_info(f"{file_name} file is updated successfully.")
    else:
        log_info(f"Failed to update file {file_name}.")
        log_error(response.text)

def update_repository_webhook(GH_ORG_NAME, GH_NEW_REPO_NAME, BB_PROJECT_KEY, BB_REPO_NAME, PIPELINE_TYPE):
    """ Update the repository webhook """
    if PIPELINE_TYPE == "Platform_Jenkins" or PIPELINE_TYPE == "Old_Jenkins":
        # GitHub API URL
        api_url = f"https://api.github.com/repos/{GH_ORG_NAME}/{GH_NEW_REPO_NAME}/hooks"

        if PIPELINE_TYPE == "Platform_Jenkins":
            WEBHOOK_URL = "https://platform-jenkins.pruconnect.net/jenkins/github-webhook/"
        elif PIPELINE_TYPE == "Old_Jenkins":
            WEBHOOK_URL = "https://jenkins.pruconnect.net/github-webhook/"
        
        # Request body
        payload = {
            "name": "web",
            "active": True,
            "events": ["push", "pull_request", "create", "delete"],
            "config": {
                "url": WEBHOOK_URL,
                "content_type": "json",
                "insecure_ssl": "0"
            }
        }

        # Make POST request to create webhook
        response = requests.post(api_url, headers=headers, json=payload)

        # Check if request was successful
        if response.status_code == 201:
            log_info(f"Webhook created successfully for the repository '{GH_NEW_REPO_NAME}'.")
        else:
            log_info(f"Failed to create webhook for the repository '{GH_NEW_REPO_NAME}'.")
            log_error(response.text)

def remove_repo_admin(GH_ORG_NAME, GH_NEW_REPO_NAME):
    # remove admin from the repository
    admins = ["SRVPSSAPRBITBUCKET01_pru"]
    url = f"https://api.github.com/repos/{GH_ORG_NAME}/{GH_NEW_REPO_NAME}/collaborators"
    for admin in admins:
        response = requests.delete(f"{url}/{admin}", headers=headers)
        if response.status_code == 204:
            log_info(f"Admin '{admin}' removed from the repository '{GH_NEW_REPO_NAME}' successfully.")
        else:
            log_error(f"Failed to remove admin '{admin}' from the repository '{GH_NEW_REPO_NAME}'. Status code: {response.status_code}")
            log_error(response.text)
            sys.exit(1)


def main():
    # Process the input from the workflow
    parser = argparse.ArgumentParser(description='Migrate Bitbucket repositories to GitHub')
    parser.add_argument('--bb-project-key', help='Bitbucket project key', required=True)
    parser.add_argument('--bb-repo-name', help='Bitbucket repo name', required=True)
    parser.add_argument('--project-code', help='PruCore project code', required=True)
    parser.add_argument('--gh-dest-org', help='GitHub dest org name', required=True)
    parser.add_argument('--gh-token', help='GitHub org token', required=True)
    parser.add_argument('--pipeline-type', help='Pipeline type', required=True)
    parser.add_argument('--user-defined-name', help='User defined name', required=True)
    args = parser.parse_args()
    process_input(args.bb_project_key, args.bb_repo_name, args.project_code, args.gh_dest_org, args.pipeline_type, args.user_defined_name)

if __name__ == '__main__':
    main()
