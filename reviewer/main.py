import os
import requests
import openai
import json
import re
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Try to import config, fallback to default if not found
try:
    from review_config import REVIEW_CONFIG
except ImportError:
    print("⚠️  review_config.py not found, using default configuration")
    REVIEW_CONFIG = {
        "skip_files": ["*.md", "*.json", "package-lock.json", "*.min.js", "dist/*"],
        "focus_on": [],
        "review_rules": [
            "Focus on security vulnerabilities and potential bugs",
            "Check for proper error handling and edge cases",
            "Verify input validation and sanitization",
        ],
        "skip_topics": [],
        "min_severity": "medium",
        "max_comments_per_file": 5,
        "tone": "balanced",
    }

# --- OpenAI Client Setup ---
client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# --- GitHub Setup ---
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
REPO = os.environ.get("GITHUB_REPO")
PR_NUMBER = os.environ.get("GITHUB_PR_NUMBER")

headers = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}


def fetch_pr_files():
    """Fetch all files changed in the PR"""
    url = f"https://api.github.com/repos/{REPO}/pulls/{PR_NUMBER}/files"
    r = requests.get(url, headers=headers)
    r.raise_for_status()
    return r.json()


def should_skip_file(filename):
    """Check if file should be skipped based on configuration"""
    import fnmatch
    
    # Check skip patterns
    for pattern in REVIEW_CONFIG["skip_files"]:
        if fnmatch.fnmatch(filename, pattern):
            return True
    
    # If focus_on is specified, only review those files
    if REVIEW_CONFIG["focus_on"]:
        matches_focus = False
        for pattern in REVIEW_CONFIG["focus_on"]:
            if fnmatch.fnmatch(filename, pattern):
                matches_focus = True
                break
        if not matches_focus:
            return True
    
    return False


def build_custom_prompt(filename, patch):
    """Build a customized prompt based on review configuration"""
    
    prompt = f"""You are a senior software engineer reviewing a pull request.

Review the following changes in `{filename}`:

```diff
{patch}
```

"""
    
    # Add custom review rules
    if REVIEW_CONFIG["review_rules"]:
        prompt += "\n**Review Priorities:**\n"
        for rule in REVIEW_CONFIG["review_rules"]:
            prompt += f"- {rule}\n"
    
    # Add topics to avoid
    if REVIEW_CONFIG["skip_topics"]:
        prompt += "\n**DO NOT comment on:**\n"
        for topic in REVIEW_CONFIG["skip_topics"]:
            prompt += f"- {topic}\n"
    
    # Add tone guidance
    tone_guidance = {
        "strict": "Be thorough and critical. Point out all potential issues without sugar-coating.",
        "balanced": "Be constructive and professional. Point out issues but also acknowledge good practices.",
        "encouraging": "Be supportive and positive. Focus on the most important issues and frame feedback constructively."
    }
    prompt += f"\n**Tone:** {tone_guidance.get(REVIEW_CONFIG['tone'], tone_guidance['balanced'])}\n"
    
    # Add severity requirement
    severity_guidance = {
        "critical": "Only flag critical security vulnerabilities or bugs that will cause failures.",
        "high": "Flag critical and high-severity issues (security, bugs, major performance problems).",
        "medium": "Flag medium-to-critical issues (bugs, security, performance, major code quality issues).",
        "low": "Flag all issues including minor code quality improvements."
    }
    prompt += f"\n**Minimum Severity:** {severity_guidance.get(REVIEW_CONFIG['min_severity'], severity_guidance['medium'])}\n"
    
    # Final instructions
    prompt += f"""
**Instructions:**
1. Analyze ONLY lines that were ADDED (lines starting with '+' in the diff)
2. Identify up to {REVIEW_CONFIG['max_comments_per_file']} specific issues that need improvement
3. For each issue, provide the EXACT line number from the NEW version of the file
4. Be specific and actionable in your comments
5. Include severity level: [CRITICAL], [HIGH], [MEDIUM], or [LOW]

**Response Format (JSON only):**
[
  {{
    "line": <line_number>,
    "severity": "<critical|high|medium|low>",
    "comment": "<specific, actionable comment with [SEVERITY] prefix>"
  }}
]

Example:
[
  {{
    "line": 42,
    "severity": "high",
    "comment": "[HIGH] This API call lacks authentication. Add token validation before processing the request."
  }}
]

Return ONLY the JSON array. If no issues found, return an empty array: []
"""
    
    return prompt


def review_file_with_openai(filename, patch):
    """Use OpenAI to review a file's changes and suggest improvements"""
    
    prompt = build_custom_prompt(filename, patch)

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a precise, helpful code reviewer. Always respond with valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
        )

        content = response.choices[0].message.content.strip()
        
        # Extract JSON from markdown code blocks if present
        if content.startswith("```"):
            content = re.sub(r'^```(?:json)?\s*\n', '', content)
            content = re.sub(r'\n```\s*$', '', content)
        
        suggestions = json.loads(content)
        
        # Validate the response format
        if not isinstance(suggestions, list):
            print(f"⚠️  Invalid response format for {filename}: not a list")
            return []
        
        # Filter by severity threshold
        severity_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        min_level = severity_order.get(REVIEW_CONFIG["min_severity"], 2)
        
        filtered = []
        for s in suggestions:
            severity = s.get("severity", "medium").lower()
            if severity_order.get(severity, 0) >= min_level:
                filtered.append(s)
        
        return filtered

    except json.JSONDecodeError as e:
        print(f"⚠️  Failed to parse JSON response for {filename}: {e}")
        return []
    except Exception as e:
        print(f"⚠️  Error reviewing {filename}: {e}")
        return []


def find_position_in_diff(file, target_line):
    """
    GitHub API requires 'position' — the line index in the diff (1-based).
    This maps a line number from the new file to its position in the patch.
    """
    patch = file.get("patch", "")
    if not patch:
        return None

    patch_lines = patch.splitlines()
    position = 0
    current_new_line = 0

    for line in patch_lines:
        position += 1

        # Parse hunk header to get starting line number
        if line.startswith("@@"):
            match = re.search(r'\+(\d+)', line)
            if match:
                current_new_line = int(match.group(1)) - 1
            continue

        # Track line numbers for added or context lines
        if line.startswith("+") and not line.startswith("+++"):
            current_new_line += 1
            if current_new_line == target_line:
                return position
        elif line.startswith("-") or line.startswith("\\"):
            continue
        else:
            current_new_line += 1

    return None


def build_review_comments(files):
    """Generate review comments for all changed files"""
    review_comments = []
    files_reviewed = 0
    files_skipped = 0

    for file in files:
        filename = file["filename"]
        patch = file.get("patch")

        # Check if file should be skipped
        if should_skip_file(filename):
            print(f"⏭️  Skipping {filename} (matches skip pattern)")
            files_skipped += 1
            continue

        # Skip files without patches
        if not patch:
            print(f"⏭️  Skipping {filename} (no patch available)")
            files_skipped += 1
            continue

        print(f"🔍 Reviewing {filename}...")
        suggestions = review_file_with_openai(filename, patch)
        files_reviewed += 1

        if not suggestions:
            print(f"  ✓ No issues found")
            continue

        for suggestion in suggestions:
            line = suggestion.get("line")
            comment = suggestion.get("comment")

            if not line or not comment:
                continue

            position = find_position_in_diff(file, line)

            if position is None:
                print(f"⚠️  Could not find line {line} in diff for {filename}")
                continue

            review_comments.append({
                "path": filename,
                "position": position,
                "body": comment
            })
            severity = suggestion.get("severity", "medium").upper()
            print(f"  ✓ [{severity}] Comment added for line {line}")

    print(f"\n📊 Review Summary: {files_reviewed} reviewed, {files_skipped} skipped")
    return review_comments


def post_inline_review(comments):
    """Post inline review comments to GitHub PR"""
    if not comments:
        print("ℹ️  No inline comments to post.")
        return True

    url = f"https://api.github.com/repos/{REPO}/pulls/{PR_NUMBER}/reviews"
    payload = {
        "body": "🤖 **AI Code Review**\n\nI've reviewed the changes and left some inline suggestions below:",
        "event": "COMMENT",
        "comments": comments
    }

    print(f"\n📤 Posting {len(comments)} inline comment(s) to PR #{PR_NUMBER}...")
    r = requests.post(url, headers=headers, json=payload)

    if r.status_code == 200:
        print("✅ Inline review comments posted successfully!")
        return True
    elif r.status_code == 403:
        print("⚠️  Permission denied (403). Trying fallback method...")
        print("\n🔧 TO FIX: Add to your GitHub Actions workflow:")
        print("   permissions:")
        print("     pull-requests: write")
        print("     contents: read")
        print("\n💡 Attempting to post individual comments instead...")
        return post_individual_comments(comments)
    else:
        print(f"❌ Failed to post review: {r.status_code}")
        print(f"Response: {r.text}")
        return False


def post_individual_comments(comments):
    """Fallback: Post comments individually"""
    url = f"https://api.github.com/repos/{REPO}/pulls/{PR_NUMBER}/comments"
    
    success_count = 0
    failed_count = 0
    
    for comment in comments:
        payload = {
            "body": f"🤖 **AI Review:** {comment['body']}",
            "path": comment["path"],
            "position": comment["position"]
        }
        
        r = requests.post(url, headers=headers, json=payload)
        
        if r.status_code == 201:
            success_count += 1
            print(f"  ✓ Posted comment on {comment['path']}")
        else:
            failed_count += 1
            print(f"  ✗ Failed to post comment on {comment['path']}: {r.status_code}")
            if r.status_code == 403:
                print(f"    Error: {r.json().get('message', 'Permission denied')}")
    
    if success_count > 0:
        print(f"\n✅ Successfully posted {success_count}/{len(comments)} comment(s) individually!")
        return True
    else:
        print("\n❌ Could not post any comments. Please check your GitHub Actions permissions.")
        return False


def main():
    """Main execution flow"""
    try:
        # Validate required environment variables
        required_vars = {
            "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY"),
            "GITHUB_TOKEN": os.environ.get("GITHUB_TOKEN"),
            "GITHUB_REPO": os.environ.get("GITHUB_REPO"),
            "GITHUB_PR_NUMBER": os.environ.get("GITHUB_PR_NUMBER")
        }
        
        missing_vars = [var for var, value in required_vars.items() if not value]
        
        if missing_vars:
            print("❌ Missing required environment variables:")
            for var in missing_vars:
                print(f"   - {var}")
            print("\n💡 Create a .env file with:")
            print("   OPENAI_API_KEY=your_openai_key")
            print("   GITHUB_TOKEN=your_github_token")
            print("   GITHUB_REPO=username/repo-name")
            print("   GITHUB_PR_NUMBER=123")
            print("\nOr export them in your terminal.")
            return
        
        print("=" * 60)
        print(f"🚀 Starting AI PR Review for {REPO} PR #{PR_NUMBER}")
        print("=" * 60)

        print("\n📥 Fetching PR files...")
        files = fetch_pr_files()
        print(f"Found {len(files)} changed file(s)")

        print("\n🧠 Generating review comments with OpenAI...")
        review_comments = build_review_comments(files)

        if review_comments:
            print(f"\n💬 Generated {len(review_comments)} total comment(s)")
            success = post_inline_review(review_comments)
            if not success:
                print("\n⚠️  Some comments could not be posted. Check permissions above.")
        else:
            print("\n✨ No issues found! The code looks good.")

        print("\n" + "=" * 60)
        print("✅ Review complete!")
        print("=" * 60)

    except requests.exceptions.RequestException as e:
        print(f"\n❌ Network error: {e}")
        raise
    except Exception as e:
        print(f"\n❌ Error during review: {e}")
        raise


if __name__ == "__main__":
    main()