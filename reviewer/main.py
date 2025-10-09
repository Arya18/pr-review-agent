import os
import requests
import openai

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
    url = f"https://api.github.com/repos/{REPO}/pulls/{PR_NUMBER}/files"
    r = requests.get(url, headers=headers)
    return r.json()


def review_file_with_openai(filename, patch):
    prompt = f"""
You are a senior software engineer reviewing a pull request.

Here is the diff patch for `{filename}`:
{patch}

Please identify up to 3 specific lines that may need improvement.

Respond with a list of objects in this format:
[
  {{ "line": <line_number>, "comment": "<comment>" }},
  ...
]

Only suggest valid and useful inline comments. Use line numbers from the "new" version of the file.
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a precise, helpful code reviewer."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3,
    )

    try:
        return eval(response.choices[0].message.content.strip())
    except Exception:
        return []


def build_review_comments(files):
    review_comments = []

    for file in files:
        filename = file["filename"]
        patch = file.get("patch")

        if not patch:
            continue  # Skip binary files or deletions

        suggestions = review_file_with_openai(filename, patch)

        for suggestion in suggestions:
            line = suggestion.get("line")
            comment = suggestion.get("comment")

            if line and comment:
                review_comments.append({
                    "path": filename,
                    "position": find_position_in_diff(file, line),
                    "body": comment
                })

    return review_comments


def find_position_in_diff(file, target_line):
    """
    GitHub API requires 'position' — the line offset in the diff, not the actual line number.
    This function maps a line number in the 'new' file to a position in the patch.
    """

    patch_lines = file.get("patch", "").splitlines()
    position = 0
    current_line = None

    new_line_num = None
    for line in patch_lines:
        position += 1

        if line.startswith("@@"):
            # Extract new line start
            hunk_header = line.split("@@")[1]
            try:
                old_info, new_info = hunk_header.strip().split(" ")
                start_line = int(new_info.split(",")[0].replace("+", ""))
                current_line = start_line - 1
            except Exception:
                continue
        elif line.startswith("+") and not line.startswith("+++"):
            current_line += 1
            if current_line == target_line:
                return position

        elif not line.startswith("-"):
            current_line += 1

    return None  # line not found in diff


def post_inline_review(comments):
    if not comments:
        print("No inline comments to post.")
        return

    url = f"https://api.github.com/repos/{REPO}/pulls/{PR_NUMBER}/reviews"
    payload = {
        "body": "AI code review suggestions below 👇",
        "event": "COMMENT",
        "comments": comments
    }

    r = requests.post(url, headers=headers, json=payload)

    if r.status_code == 200:
        print("✅ Inline review comments posted.")
    else:
        print(f"❌ Failed to post review: {r.status_code}\n{r.text}")


def main():
    print("🔍 Fetching PR files...")
    files = fetch_pr_files()

    print("🧠 Generating review comments with OpenAI...")
    review_comments = build_review_comments(files)

    print("📝 Posting comments to GitHub...")
    post_inline_review(review_comments)


if __name__ == "__main__":
    main()
