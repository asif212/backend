# Nial.in portfolio migration

The import is restricted to the five portfolio categories and their published gallery groups and images. It does not import blog posts, software articles, general pages, comments, users or WordPress plugin functionality.

The local import contains 10 parent/child sections and 181 gallery image placements, including nine animated GIFs. WordPress's media optimizations and mobile/desktop gallery repeats are resolved to local files; duplicate entries within each section are removed. The full backup remains separate from public application assets.

Runtime data lives in `website_data/portfolio.json` and `website_data/portfolio_assets/`. Administrators can edit it through **Website content → Portfolio manager**. The existing MyTime database is not altered. A private rollback snapshot is stored in the ignored `website_import_backups/` directory.

The offline importer reads the original .wpress headers and MySQL literal values without executing SQL or PHP. It reads Elementor's portfolio groups, checks images against the published portfolio pages, optimizes still images, and preserves animation for GIFs. For this Nial.in export, source WordPress IDs are mapped to the five existing category IDs in `import_wordpress.py`.

To prepare another import from the same source schema:

```sh
PYTHONPATH=src ../venv/bin/python -m my_time.import_wordpress \
  --source /absolute/path/to/backup.wpress \
  --output /absolute/path/to/new-empty-staging-directory
```

Inspect the staging report before using `--apply`. Applying merges records by stable IDs, takes a private website snapshot, and preserves existing edits. It does not publish to the live nial.in site or change DNS/hosting.

## Included public assets

The repository includes website_data/content.json, portfolio.json, the homepage work images, and the portfolio_assets WebP/GIF images. A fresh clone contains the public gallery without needing the original WordPress backup. Keep this directory persistent and writable on the backend host; set WEBSITE_DATA_DIR to its absolute path if the server starts elsewhere. Subsequent administrator uploads change runtime data and need their own backup or explicit Git commit. Do not overwrite newer production uploads with an older checkout.

The .gitignore rules allow only these public files. Google OAuth credentials, lock files, import reports, database files, and private backups remain excluded.
