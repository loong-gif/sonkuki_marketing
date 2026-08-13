#!/bin/bash
# Wait for NocoDB (72.52.161.65:8080) to come back, then exit 0.
TOK=$(grep 'NocoDB PAT' /Users/wyl/sonkuki/credentials.txt | cut -d: -f2 | tr -d ' ')
for i in $(seq 1 120); do
  CODE=$(curl -s --noproxy '*' --max-time 10 -o /dev/null -w "%{http_code}" \
    "http://72.52.161.65:8080/api/v1/db/meta/projects/p447va1t8jqqjty/tables" \
    -H "xc-token: $TOK")
  if [ "$CODE" = "200" ]; then
    echo "NocoDB is back (after ${i} checks)"
    exit 0
  fi
  sleep 30
done
echo "NocoDB still down after 60 minutes"
exit 1
