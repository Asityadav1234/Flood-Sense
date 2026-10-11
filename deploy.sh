#!/usr/bin/env bash
# One-command deploy: backend (Lambda container + Function URL + DynamoDB), frontend (S3 + CloudFront).
# Needs: AWS CLI (logged in), AWS SAM CLI, Docker (running), Node 18+.
set -euo pipefail
cd "$(dirname "$0")"
STACK=${STACK:-floodsense}
REGION=${AWS_REGION:-us-east-1}   # keep us-east-1: Bedrock Nova Lite works there without extra setup

for c in aws sam docker node npm; do command -v "$c" >/dev/null || { echo "Missing: $c"; exit 1; }; done
docker info >/dev/null 2>&1 || { echo "Docker is not running."; exit 1; }
aws sts get-caller-identity >/dev/null || { echo "AWS CLI is not logged in (run: aws configure)."; exit 1; }

sam build
sam deploy --stack-name "$STACK" --region "$REGION"

out() { aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" \
        --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }
API=$(out ApiUrl); BUCKET=$(out BucketName); DIST=$(out DistributionId); SITE=$(out SiteUrl)

(cd frontend && npm ci && VITE_API_URL="${API%/}" npm run build)
aws s3 sync frontend/dist "s3://$BUCKET" --delete --region "$REGION"
aws cloudfront create-invalidation --distribution-id "$DIST" --paths "/*" >/dev/null

echo; echo "Live at:  $SITE"; echo "API docs: ${API}docs"
echo "Health:   curl ${API}health"
