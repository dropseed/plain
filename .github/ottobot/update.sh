#/bin/bash -e

comment="$1"
instructions=$(cat << 'EOF'
You are being given feedback by the user on the changes in your last commit.

- You should respond by making adjustments in a new commit.
- Don't change anything that isn't directly related to what is being asked.
- You are only updating documentation, do not try to update source code.
- Most importantly, check your work for correctness and clarity against the source code.

Review from the user:
EOF
)

# Get the files modified in the previous commit
files=$(git diff --name-only HEAD^ HEAD | grep /plain/)

uvx --from aider-chat aider \
    -c ./.github/ottobot/aider.yml \
    --restore-chat-history \
    --yes-always \
    --message "$instructions $comment" \
    $files
