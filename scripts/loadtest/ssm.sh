#!/bin/bash
# usage: LT_TARGET=<instance-id> ssm.sh '<shell commands>'
# Runs the commands on that EC2 instance over SSM; prints status, stdout, stderr.
# AWS_PROFILE / AWS_REGION select the account (e.g. digitva / ap-south-1).
set -e
: "${LT_TARGET:?set LT_TARGET to the instance id}"
id=$(aws ssm send-command --instance-ids "$LT_TARGET" --document-name AWS-RunShellScript \
  --parameters "$(python3 -c 'import json,sys; print(json.dumps({"commands":[sys.argv[1]],"executionTimeout":["3000"]}))' "$1")" \
  --timeout-seconds 60 --query Command.CommandId --output text)
for i in $(seq 1 600); do
  s=$(aws ssm get-command-invocation --command-id "$id" --instance-id "$LT_TARGET" --query Status --output text 2>/dev/null || echo Pending)
  case $s in Success|Failed|Cancelled|TimedOut) break;; esac; sleep 2
done
aws ssm get-command-invocation --command-id "$id" --instance-id "$LT_TARGET" \
  --query '[Status,StandardOutputContent,StandardErrorContent]' --output text
