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
        Use a standalone script instead (scripts/generate_history_index.py).
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
                    'Use scripts/generate_history_index.py instead.'
                )

    def test_deploy_pages_uses_script_not_inline(self):
        """deploy-pages.yml should use generate_history_index.py, not inline Python."""
        path = WORKFLOW_DIR / 'deploy-pages.yml'
        if not path.exists():
            return

        content = path.read_text()

        has_heredoc = bool(re.search(r"python3 << 'EOF'", content))
        has_script_call = bool(
            re.search(r'python3 scripts/generate_history_index\.py', content)
        )

        assert not has_heredoc or has_script_call, (
            'deploy-pages.yml should call scripts/generate_history_index.py '
            'instead of using inline Python heredoc'
        )

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
