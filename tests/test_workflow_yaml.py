"""Validate all GitHub Actions workflow YAML files.

Ensures workflows are syntactically valid and don't contain common
patterns that break YAML parsing (e.g. inline Python f-strings with
curly braces and colons inside heredocs).
"""

import yaml
import re
from pathlib import Path


WORKFLOW_DIR = Path('.github/workflows')


def _yaml_files():
    """Yield all YAML workflow files."""
    for p in sorted(WORKFLOW_DIR.glob('*.yml')):
        yield p


class TestWorkflowYAML:
    """Tests for workflow YAML syntax and structure."""

    def test_all_workflow_files_exist(self):
        """At least one workflow file must exist."""
        files = list(_yaml_files())
        assert len(files) >= 1, f'Expected at least 1 workflow, found {len(files)}'

    def test_all_yaml_files_parse(self):
        """Every .yml file in workflows/ must be valid YAML."""
        for path in _yaml_files():
            with open(path) as f:
                try:
                    doc = yaml.safe_load(f)
                except yaml.YAMLError as exc:
                    raise AssertionError(
                        f'{path} is not valid YAML:\n{exc}'
                    )

            assert doc is not None, f'{path} parsed as empty YAML'

    def test_deploy_pages_has_no_inline_risky_heredoc(self):
        """deploy-pages.yml must NOT use inline f-string Python that breaks YAML.

        The pattern `f'''...{expr}...'''` inside a YAML heredoc can confuse
        YAML parsers when <a href="..."> and similar HTML tags appear.
        Use a standalone script instead (scripts_utils/generate_history_index.py).
        """
        path = WORKFLOW_DIR / 'deploy-pages.yml'
        if not path.exists():
            return  # skip if file doesn't exist

        content = path.read_text()

        # Flag: inline Python heredoc that uses f-strings with HTML
        has_heredoc = bool(re.search(r"python3 << 'EOF'", content))
        has_fstring_in_heredoc = bool(
            re.search(r"python3 << 'EOF'[.\n]*?f'''", content, re.DOTALL)
        )

        if has_heredoc:
            # Check that any f''' inside heredoc doesn't contain HTML tags
            fstring_match = re.search(
                r"python3 << 'EOF'\n(.*?)\n +EOF",
                content, re.DOTALL
            )
            if fstring_match:
                body = fstring_match.group(1)
                has_html_in_fstring = bool(
                    re.search(r"f'''[^']*<[aA]\s", body)
                )
                assert not has_html_in_fstring, (
                    'deploy-pages.yml: inline Python heredoc contains f-string '
                    'with HTML <a> tags. This breaks YAML parsing. '
                    'Use scripts_utils/generate_history_index.py instead.'
                )

    def test_deploy_serialises_runs(self):
        """Two overlapping deploys race on the same gh-pages commit.

        Both regenerate everything and push without --force; the loser is
        rejected non-fast-forward and its output is lost. Runs one minute apart
        have happened in this repo.
        """
        doc = yaml.safe_load((WORKFLOW_DIR / 'deploy-pages.yml').read_text())
        concurrency = doc.get('concurrency')

        assert concurrency, 'deploy-pages.yml must declare a concurrency group'
        assert concurrency.get('cancel-in-progress') is False, (
            'queue deploys rather than cancelling — cancelling mid-push is worse'
        )

    def test_deploy_runs_tests_before_publishing(self):
        """Publishing must not race the test suite.

        Without this the two run in parallel, so a commit that breaks a
        generator goes live at roughly the moment the test job turns red.
        """
        doc = yaml.safe_load((WORKFLOW_DIR / 'deploy-pages.yml').read_text())
        jobs = doc['jobs']

        assert 'deploy' in jobs, 'deploy-pages.yml must define a deploy job'
        needs = jobs['deploy'].get('needs') or []
        needs = [needs] if isinstance(needs, str) else needs
        assert needs, 'the deploy job must depend on a job that runs the tests'

        gating = ' '.join(
            step.get('run', '') for name in needs for step in jobs[name]['steps'])
        assert 'pytest' in gating, (
            f'jobs {needs} gate the deploy but none of them runs pytest')

    def test_deploy_checks_the_site_before_pushing(self):
        """A generator can fail and still leave a publishable-looking tree.

        The unconditional `git add .` then publishes it, which is how a dropped
        model and a blank history index both reached the live site with a green
        build. check_site.py compares against what is published and fails on loss.
        """
        content = (WORKFLOW_DIR / 'deploy-pages.yml').read_text()

        assert 'check_site.py' in content, (
            'deploy-pages.yml must run the pre-publish sanity check')
        assert content.index('check_site.py') < content.index('git push'), (
            'the site check must run before the push, not after')

    def test_deploy_copies_every_script_it_runs(self):
        """Scripts were copied one by one, so a new shared module would be missing
        on gh-pages and fail at import time only during a real deploy."""
        content = (WORKFLOW_DIR / 'deploy-pages.yml').read_text()

        invoked = set(re.findall(r'python3 (scripts_utils/[\w./]+\.py)', content))
        assert invoked, 'expected the workflow to invoke scripts from scripts_utils/'

        copies_whole_dir = 'git checkout master -- scripts_utils/' in content
        for script in sorted(invoked):
            assert copies_whole_dir or f'git checkout master -- {script}' in content, (
                f'deploy-pages.yml runs {script} but never checks it out')
            assert (Path('scripts_utils') / Path(script).name).exists(), (
                f'deploy-pages.yml runs {script}, which does not exist')

    def test_workflow_has_required_keys(self):
        """Each workflow must define 'name', 'on', and 'jobs'."""
        # PyYAML parses 'on' as a YAML boolean True, so check both
        for path in _yaml_files():
            with open(path) as f:
                doc = yaml.safe_load(f)

            required_checks = [
                ('name', 'name'),
                ('on', True),      # 'on' is a YAML 1.1 boolean → parsed as True
                ('jobs', 'jobs'),
            ]
            for display_name, effective_key in required_checks:
                assert effective_key in doc, (
                    f'{path}: missing required key "{display_name}"'
                )

    def test_jobs_have_runs_on_or_uses(self):
        """Every job must specify 'runs-on' or 'uses'."""
        for path in _yaml_files():
            with open(path) as f:
                doc = yaml.safe_load(f)

            for job_name, job_def in doc.get('jobs', {}).items():
                assert 'runs-on' in job_def or 'uses' in job_def, (
                    f'{path}: job "{job_name}" must have "runs-on" or "uses"'
                )

    def test_deploy_workflow_checks_out_scripts(self):
        """deploy-pages.yml must check out the scripts it needs."""
        path = WORKFLOW_DIR / 'deploy-pages.yml'
        if not path.exists():
            return

        content = path.read_text()

        required_scripts = [
            'scripts_utils/md_to_html.py',
            'scripts_utils/generate_history_index.py',
            'scripts_utils/generate_landing_page.py',
        ]

        for script in required_scripts:
            assert script in content, (
                f'deploy-pages.yml must check out {script}'
            )
