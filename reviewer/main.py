import os
import requests
import openai
import json
import re

# --- OpenAI Client Setup ---
client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])

# --- GitHub Setup ---
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
REPO = os.environ["GITHUB_REPO"]  # e.g., "user/repo"
PR_NUMBER = os.environ["GITHUB_PR_NUMBER"]

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


def review_file_with_openai(filename, patch):
    """Use OpenAI to review a file's changes and suggest improvements"""
    prompt = f"""
You are a senior software engineer reviewing a pull request.

Here is the diff patch for `{filename}`:
```diff
{patch}
```

Analyze the changes and identify specific issues or improvements needed.
For each issue, provide the EXACT line number from the NEW version of the file where the issue occurs.

IMPORTANT: 
- Only comment on lines that were ADDED (lines starting with '+' in the diff)
- Use the actual line numbers from the new file, not the diff position
- Focus on: bugs, security issues, performance problems, code quality, and best practices
- Be specific and constructive
- Limit to the 3-5 most important issues

Respond with ONLY a valid JSON array in this exact format:
[
  {{"line": <line_number>, "comment": "<specific, actionable comment>"}},
  ...
]

Example:
[
  {{"line": 42, "comment": "Consider adding error handling for the API call to prevent unhandled exceptions."}},
  {{"line": 55, "comment": "This variable name 'x' is not descriptive. Consider renaming to 'user_count' for clarity."}}
]
"""

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
        
        return suggestions

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
            # Format: @@ -old_start,old_count +new_start,new_count @@
            match = re.search(r'\+(\d+)', line)
            if match:
                current_new_line = int(match.group(1)) - 1
            continue

        # Track line numbers for added or context lines
        if line.startswith("+") and not line.startswith("+++"):
            # This is an added line
            current_new_line += 1
            if current_new_line == target_line:
                return position
        elif line.startswith("-") or line.startswith("\\"):
            # Deleted lines don't increment new line counter
            continue
        else:
            # Context line (no prefix or space prefix)
            current_new_line += 1

    return None


def build_review_comments(files):
    """Generate review comments for all changed files"""
    review_comments = []

    for file in files:
        filename = file["filename"]
        patch = file.get("patch")

        # Skip files without patches (binary, deleted, or too large)
        if not patch:
            print(f"⏭️  Skipping {filename} (no patch available)")
            continue

        print(f"🔍 Reviewing {filename}...")
        suggestions = review_file_with_openai(filename, patch)

        for suggestion in suggestions:
            line = suggestion.get("line")
            comment = suggestion.get("comment")

            if not line or not comment:
                continue

            # Find the position in the diff for this line
            position = find_position_in_diff(file, line)

            if position is None:
                print(f"⚠️  Could not find line {line} in diff for {filename}")
                continue

            review_comments.append({
                "path": filename,
                "position": position,
                "body": comment
            })
            print(f"  ✓ Comment added for line {line} (position {position})")

    return review_comments


def post_inline_review(comments):
    """Post inline review comments to GitHub PR"""
    if not comments:
        print("ℹ️  No inline comments to post.")
        return

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
    else:
        print(f"❌ Failed to post review: {r.status_code}")
        print(f"Response: {r.text}")
        raise Exception(f"GitHub API error: {r.status_code}")


def main():
    """Main execution flow"""
    try:
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
            post_inline_review(review_comments)
        else:
            print("\n✨ No issues found! The code looks good.")

        print("\n" + "=" * 60)
        print("✅ Review complete!")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Error during review: {e}")
        raise


if __name__ == "__main__":
    main()