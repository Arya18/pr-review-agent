# review_config.py
# ========================================
# 🎯 AI PR Review Configuration
# ========================================

REVIEW_CONFIG = {
    # Files/patterns to skip (won't be reviewed at all)
    "skip_files": [
        "*.md",           # Skip markdown files
        "*.json",         # Skip JSON files
        "package-lock.json",
        "*.yml",
        "yarn.lock",
        "*.min.js",       # Skip minified files
        "*.test.js",      # Skip test files (optional)
        "*.spec.js",
        "dist/*",         # Skip build/dist folders
        "build/*",
        "node_modules/*",
    ],
    
    # Paths to focus on (if empty, reviews all non-skipped files)
    "focus_on": [
        # "src/",         # Only review src folder
        # "lib/*.py",     # Only Python files in lib
    ],
    
    # Custom review rules and priorities
    "review_rules": [
        "Focus on security vulnerabilities and potential bugs",
        "Check for proper error handling and edge cases",
        "Verify input validation and sanitization",
        "Look for performance issues (N+1 queries, inefficient loops)",
        "Ensure code follows DRY principle (Don't Repeat Yourself)",
        "Check for hardcoded credentials or sensitive data",
        "Verify proper resource cleanup (file handles, connections)",
    ],
    
    # Topics to AVOID reviewing
    "skip_topics": [
        # "code style and formatting",  # Don't comment on formatting
        # "variable naming",             # Don't comment on names
        # "comments and documentation",  # Don't ask for more comments
        # "test coverage",               # Don't ask for tests
    ],
    
    # Severity threshold (only report issues of this level or higher)
    # Options: "critical", "high", "medium", "low"
    "min_severity": "medium",
    
    # Maximum comments per file
    "max_comments_per_file": 5,
    
    # Review tone
    # Options: "strict", "balanced", "encouraging"
    "tone": "balanced",
}