import os
import openai
import requests

# Initialize OpenAI client using new SDK (>=1.0.0)
client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])

# GitHub environment variables provided via GitHub Actions
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
REPO = os.environ["GITHUB_REPO"]
PR_NUMBER = os.environ["GITHUB_PR_NUMBER"]

headers = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}


def fetch_pr_diff():
    # Fetch PR metadata
    url = f"https://api.github.com/repos/{REPO}/pulls/{PR_NUMBER}"
    r = requests.get(url, headers=headers)
    pr_data = r.json()

    title = pr_data["title"]
    body = pr_data.get("body", "")

    # Fetch the diff (patch)
    diff_url = pr_data["patch_url"]
    r = requests.get(diff_url, headers=headers)
    diff_text = r.text

    return title, body, diff_text


def review_with_openai(title, body, diff):
    prompt = f"""
You are a senior software engineer reviewing a GitHub pull request.

Pull Request Title: {title}
Description: {body}

Here is the code diff:
{diff}

Please provide:
- A high-level summary of the PR
- Any issues, bugs, or concerns
- Suggestions for improvements
- Comments on code readability, naming, structure
- Test or documentation requirements

Keep the tone constructive and professional.
"""

    # Use new SDK: client.chat.completions.create()
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are an experienced code reviewer."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3,
    )

    return response.choices[0].message.content


def post_comment_to_pr(comment):
    # Post a summary comment to the PR
    url = f"https://api.github.com/repos/{REPO}/issues/{PR_NUMBER}/comments"
    payload = {"body": comment}
    r = requests.post(url, headers=headers, json=payload)
    if r.status_code == 201:
        print("✅ Comment posted to PR")
    else:
        print(f"❌ Failed to post comment: {r.status_code}\n{r.text}")


def main():
    title, body, diff = fetch_pr_diff()
    review = review_with_openai(title, body, diff)
    post_comment_to_pr(review)


if __name__ == "__main__":
    main()
