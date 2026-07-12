#!/usr/bin/env python3
"""
GitHub repository monitoring script.

Checks for:
1. New issues
2. PR comments/reviews
3. Approved PRs (auto-merge)
"""

import sys
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
import requests

WORKSPACE = Path("/home/node/.openclaw/workspace")
REPO = "Kickoman/rain-analysis"
STATE_FILE = WORKSPACE / "memory/heartbeat-state.json"

def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"lastChecks": {}}

def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

def get_github_token():
    creds = WORKSPACE / "github_credentials.json"
    with open(creds) as f:
        return json.load(f)['github_token']

def check_issues(token, since_ts):
    """Check for new or updated issues."""
    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json'
    }
    
    since = datetime.fromtimestamp(since_ts, timezone.utc).isoformat()
    url = f"https://api.github.com/repos/{REPO}/issues"
    params = {'state': 'open', 'since': since, 'sort': 'updated', 'direction': 'desc'}
    
    r = requests.get(url, headers=headers, params=params, timeout=10)
    if r.status_code != 200:
        return []
    
    issues = [i for i in r.json() if 'pull_request' not in i]
    return issues

def check_prs(token, since_ts):
    """Check for new or updated PRs."""
    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json'
    }
    
    url = f"https://api.github.com/repos/{REPO}/pulls"
    params = {'state': 'open', 'sort': 'updated', 'direction': 'desc'}
    
    r = requests.get(url, headers=headers, params=params, timeout=10)
    if r.status_code != 200:
        return []
    
    prs = r.json()
    since_dt = datetime.fromtimestamp(since_ts, timezone.utc)
    recent = [pr for pr in prs if datetime.fromisoformat(pr['updated_at'].replace('Z', '+00:00')) > since_dt]
    
    return recent

def check_pr_reviews(token, pr_number):
    """Check if PR is approved."""
    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json'
    }
    
    url = f"https://api.github.com/repos/{REPO}/pulls/{pr_number}/reviews"
    r = requests.get(url, headers=headers, timeout=10)
    if r.status_code != 200:
        return False
    
    reviews = r.json()
    # Check if any review is APPROVED
    return any(rev['state'] == 'APPROVED' for rev in reviews)

def merge_pr(token, pr_number):
    """Merge an approved PR."""
    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json'
    }
    
    url = f"https://api.github.com/repos/{REPO}/pulls/{pr_number}/merge"
    data = {'merge_method': 'merge'}
    
    r = requests.put(url, headers=headers, json=data, timeout=10)
    return r.status_code == 200

def main():
    state = load_state()
    token = get_github_token()
    
    now = datetime.now(timezone.utc).timestamp()
    last_check = state['lastChecks'].get('github_prs', now - 3600 * 4)
    
    print(f"=== GitHub Check: {datetime.now(timezone.utc).isoformat()} ===")
    
    # Check issues
    issues = check_issues(token, last_check)
    if issues:
        print(f"\n📋 {len(issues)} issue(s) updated:")
        for issue in issues:
            print(f"  #{issue['number']}: {issue['title']}")
    
    # Check PRs
    prs = check_prs(token, last_check)
    if prs:
        print(f"\n🔀 {len(prs)} PR(s) updated:")
        for pr in prs:
            print(f"  #{pr['number']}: {pr['title']}")
            
            # Check if approved
            if check_pr_reviews(token, pr['number']):
                print(f"    ✅ APPROVED — merging...")
                if merge_pr(token, pr['number']):
                    print(f"    ✓ Merged #{pr['number']}")
                else:
                    print(f"    ✗ Failed to merge #{pr['number']}")
    
    if not issues and not prs:
        print("✓ No updates")
    
    # Update state
    state['lastChecks']['github_issues'] = now
    state['lastChecks']['github_prs'] = now
    save_state(state)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
