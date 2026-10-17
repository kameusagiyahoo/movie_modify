# yomiyasu integration

Source: https://github.com/nanaism/yomiyasu
Pinned source commit: 1bc21f9c8e6a55fc4ccd5a2c7dfe78a7b0d814c5
Entry point: `.agents/skills/yomiyasu/SKILL.md`
License: MIT (see the vendored LICENSE and UNICODE-LICENSE.txt).

## Why here?

yomiyasu refines Japanese prose written by agents. Use it for Japanese
README files, technical explanations, UI guidance and PR descriptions.
It is NOT a video analysis tool, caption generator, or automatic editor.
No media file is passed to yomiyasu by the Movie Modify backend.

Codex can discover the skill from the `.agents/skills/` directory.
Invoke `/yomiyasu` after writing Japanese, or instruct your agent to
review a document using yomiyasu and preserve meaning and numbers.

## Optional offline verification

The vendored Python scripts do not call LLM APIs. After creating source
and reviewed Markdown documents, run:

```bash
python3 .agents/skills/yomiyasu/scripts/yomiyasu_lint.py docs/draft.md
python3 .agents/skills/yomiyasu/scripts/yomiyasu_diff.py docs/draft.md docs/revised.md
python3 .agents/skills/yomiyasu/scripts/yomiyasu_check.py run --source docs/draft.md --final docs/revised.md --doc-type manual
python3 .agents/skills/yomiyasu/scripts/yomiyasu_check.py verify --final docs/revised.md
```

The scripts flag potential issues; they do not prove semantic equivalence.
The skill may generate state files in .yomiyasu/, which are gitignored.

## Updating

The snapshot is not automatically updated.
On a trusted development machine run `bash scripts/update-yomiyasu.sh`
to sync from upstream. Check the changes and licenses before committing.
Update the source commit recorded above when refreshing.
