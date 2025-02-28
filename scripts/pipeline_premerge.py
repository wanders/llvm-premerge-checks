#!/usr/bin/env python3
# Copyright 2020 Google LLC
#
# Licensed under the the Apache License v2.0 with LLVM Exceptions (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://llvm.org/LICENSE.txt
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
import os

from buildkite_utils import annotate, feedback_url, set_metadata
from choose_projects import ChooseProjects
import git
from steps import generic_linux, generic_windows, from_shell_output, checkout_scripts
import yaml

steps_generators = [
    '${BUILDKITE_BUILD_CHECKOUT_PATH}/libcxx/utils/ci/buildkite-pipeline-premerge.sh',
]

if __name__ == '__main__':
    scripts_refspec = os.getenv("ph_scripts_refspec", "main")
    diff_id = os.getenv("ph_buildable_diff", "")
    no_cache = os.getenv('ph_no_cache') is not None
    projects = os.getenv('ph_projects', 'detect')
    log_level = os.getenv('ph_log_level', 'INFO')
    logging.basicConfig(level=log_level, format='%(levelname)-7s %(message)s')

    phid = os.getenv('ph_target_phid')
    url = f"https://reviews.llvm.org/D{os.getenv('ph_buildable_revision')}?id={diff_id}"
    annotate(f"Build for [D{os.getenv('ph_buildable_revision')}#{diff_id}]({url}). "
             f"[Harbormaster build](https://reviews.llvm.org/harbormaster/build/{os.getenv('ph_build_id')}).\n"
             f"If there is a build infrastructure issue, please [create a bug]({feedback_url()}).")
    set_metadata('ph_buildable_diff', os.getenv("ph_buildable_diff"))
    set_metadata('ph_buildable_revision', os.getenv('ph_buildable_revision'))
    set_metadata('ph_build_id', os.getenv("ph_build_id"))
    # List all affected projects.
    repo = git.Repo('.')
    patch = repo.git.diff("HEAD~1")
    cp = ChooseProjects('.')
    modified_files = cp.get_changed_files(patch)
    modified_projects, unmapped_changes = cp.get_changed_projects(modified_files)
    if unmapped_changes:
        logging.warning('There were changes that could not be mapped to a project. Checking everything')
        modified_projects = cp.all_projects
    logging.info(f'modified projects: {modified_projects}')
    # Add projects that depend on modified.
    affected_projects = cp.get_affected_projects(modified_projects)
    steps = []
    projects = cp.add_dependencies(affected_projects)
    logging.info(f'projects with dependencies: {projects}')
    # Add generic Linux checks.
    excluded_linux = cp.get_excluded('linux')
    logging.info(f'excluded for linux: {excluded_linux}')
    linux_projects = projects - excluded_linux
    if len(linux_projects) > 0:
        steps.extend(generic_linux(';'.join(sorted(linux_projects)), True))
    # Add generic Windows steps.
    excluded_windows = cp.get_excluded('windows')
    logging.info(f'excluded for windows: {excluded_windows}')
    windows_projects = projects - excluded_windows
    if len(windows_projects) > 0:
        steps.extend(generic_windows(';'.join(sorted(windows_projects))))
    # Add custom checks.
    if os.getenv('ph_skip_generated') is None:
        for gen in steps_generators:
            steps.extend(from_shell_output(gen))

    if phid is None:
        logging.warning('ph_target_phid is not specified. Skipping "Report" step')
    else:
        steps.append({
            'wait': '~',
            'continue_on_failure': True,
        })

        report_step = {
            'label': ':phabricator: update build status on Phabricator',
            'commands': [
                *checkout_scripts('linux', scripts_refspec),
                '$${SRC}/scripts/summary.py',
            ],
            'artifact_paths': ['artifacts/**/*'],
            'agents': {'queue': 'service'},
            'timeout_in_minutes': 10,
        }
        steps.append(report_step)

    print(yaml.dump({'steps': steps}))
