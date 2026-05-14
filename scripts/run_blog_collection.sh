#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SKILL_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
COLLECTOR="$SCRIPT_DIR/collect_security_blogs.py"
OUTPUT_DIR=${OUTPUT_DIR:-"$SKILL_DIR/output"}
TIMESTAMP=$(date -u +"%Y%m%d-%H%M%SZ")

JSON_OUT="$OUTPUT_DIR/security-blog-digest-$TIMESTAMP.json"
MD_OUT="$OUTPUT_DIR/security-blog-digest-$TIMESTAMP.md"
LATEST_JSON="$OUTPUT_DIR/latest-security-blog-digest.json"
LATEST_MD="$OUTPUT_DIR/latest-security-blog-digest.md"

mkdir -p "$OUTPUT_DIR"

TOPIC_CLASSIFIER=${TOPIC_CLASSIFIER:-auto}
LLM_PROVIDER=${LLM_PROVIDER:-auto}
PER_SOURCE=${PER_SOURCE:-5}
SINCE_DAYS=${SINCE_DAYS:-30}
LIMIT_SOURCES=${LIMIT_SOURCES:-}
SOURCE_FILTER=${SOURCE_FILTER:-}
KEYWORDS=${KEYWORDS:-}
ALL_TOPICS=${ALL_TOPICS:-0}

set -- --topic-classifier "$TOPIC_CLASSIFIER" --llm-provider "$LLM_PROVIDER" --per-source "$PER_SOURCE" --since-days "$SINCE_DAYS" "$@"

if [ -n "$LIMIT_SOURCES" ]; then
  set -- --limit-sources "$LIMIT_SOURCES" "$@"
fi

if [ -n "$SOURCE_FILTER" ]; then
  set -- --source-filter "$SOURCE_FILTER" "$@"
fi

if [ -n "$KEYWORDS" ]; then
  set -- --keywords "$KEYWORDS" "$@"
fi

if [ "$ALL_TOPICS" = "1" ]; then
  set -- --all-topics "$@"
fi

printf 'Collector: %s\n' "$COLLECTOR"
printf 'Output dir: %s\n' "$OUTPUT_DIR"
printf 'Topic classifier: %s\n' "$TOPIC_CLASSIFIER"
printf 'LLM provider: %s\n' "$LLM_PROVIDER"
printf 'Since days: %s\n' "$SINCE_DAYS"
printf 'Per source: %s\n' "$PER_SOURCE"

if [ -n "${OPENAI_API_KEY:-}" ]; then
  printf 'OpenAI key: configured\n'
fi
if [ -n "${PACKY_API_KEY:-}" ]; then
  printf 'Packy key: configured\n'
fi
if [ -z "${OPENAI_API_KEY:-}" ] && [ -z "${PACKY_API_KEY:-}" ] && [ "$TOPIC_CLASSIFIER" != "keyword" ] && [ "$ALL_TOPICS" != "1" ]; then
  printf 'No LLM API key detected. Auto mode will fall back to keyword filtering.\n'
fi

python3 "$COLLECTOR" --format json --output "$JSON_OUT" "$@"
python3 "$COLLECTOR" --format markdown --output "$MD_OUT" "$@"

cp "$JSON_OUT" "$LATEST_JSON"
cp "$MD_OUT" "$LATEST_MD"

printf '\nDone.\n'
printf 'JSON: %s\n' "$JSON_OUT"
printf 'Markdown: %s\n' "$MD_OUT"
printf 'Latest JSON: %s\n' "$LATEST_JSON"
printf 'Latest Markdown: %s\n' "$LATEST_MD"
