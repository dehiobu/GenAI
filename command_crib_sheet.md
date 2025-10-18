# Command Crib Sheet

Cheat‑sheet of common AWS CLI commands and project scripts used while working on Summary Translator.

## SAM Build & Deploy

```bash
sam build
sam deploy --guided \
  --region us-east-1 \
  --parameter-overrides \
    IngestBucketName=genai-in-use1-x7p5f0 \
    OutputBucketName=genai-out-use1-x7p5f0 \
    TargetLanguage=fr \
    ModelId="anthropic.claude-3-haiku-20240307-v1:0"
```

- `sam build` — packages Lambda source and dependencies into the `.aws-sam` folder.
- `sam deploy --guided` — interactive deployment; `--parameter-overrides` supplies template parameters (buckets, model ID, target language).

## Presign Lambda IAM Policies

Attach inline policy so the download Lambda can list/get/delete outputs:

```bash
aws iam put-role-policy \
  --role-name GenerateDownloadURL-role-XXXX \
  --policy-name AllowDownloadAccess \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {"Effect":"Allow","Action":"s3:ListBucket","Resource":"arn:aws:s3:::genai-out-use1-x7p5f0"},
      {"Effect":"Allow","Action":["s3:GetObject","s3:DeleteObject"],"Resource":"arn:aws:s3:::genai-out-use1-x7p5f0/*"}
    ]
  }'
```

- `put-role-policy` — attaches a named inline policy to the Lambda execution role.
- Scope actions to the output bucket only.

## CLI Smoke Tests

Upload to ingest bucket and inspect outputs.

```bash
# Upload a sample document to trigger the pipeline
aws s3 cp sample.txt s3://genai-in-use1-x7p5f0/incoming/sample.txt --region us-east-1

# List generated summaries/translations/errors
aws s3 ls s3://genai-out-use1-x7p5f0/summaries/
aws s3 ls s3://genai-out-use1-x7p5f0/translations/
aws s3 ls s3://genai-out-use1-x7p5f0/errors/
```

- `aws s3 cp` — copies a local file into the ingest bucket.
- `aws s3 ls` — enumerates objects in the output prefixes.

## API Gateway CORS Check (DELETE preflight)

```bash
curl -i -X OPTIONS \
  -H "Origin: http://<your-host>" \
  -H "Access-Control-Request-Method: DELETE" \
  "https://r62nxdnlhi.execute-api.us-east-1.amazonaws.com/default/GenerateDownloadURL?folder=errors&filename=test.txt"
```

- Confirms API Gateway returns `Access-Control-Allow-Origin`, `Access-Control-Allow-Methods`, etc., enabling DELETE from the browser.

## Lightsail Deployment (GitHub Actions)

Workflow (`.github/workflows/deploy.yml`) uses secrets:

- `LIGHTSAIL_HOST` — instance public IP or DNS.
- `LIGHTSAIL_USER` — usually `ubuntu`.
- `LIGHTSAIL_SSH_KEY` — private key (PEM) for SCP/SSH.
- Optional `LIGHTSAIL_SSH_PORT`.

Key steps inside the workflow:

1. Checkout repository.
2. `appleboy/scp-action` — uploads `index.html` (and static assets) to `/tmp/genai-site`.
3. `appleboy/ssh-action` — rsyncs to `/var/www/html/` and reloads Apache (`systemctl reload apache2`).

## Miscellaneous

- `aws apigatewayv2 get-api --api-id <id> --query "CorsConfiguration"` — verify CORS methods/origins for the HTTP API.
- `aws iam get-role-policy --role-name <role> --policy-name <name>` — confirm inline policy attachments.
- `sam logs -n <function-name> --tail --region us-east-1` — stream Lambda logs (optional, not used above but handy).

Keep this sheet handy when updating infrastructure or troubleshooting deployment.
