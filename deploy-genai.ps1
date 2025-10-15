# deploy-genai.ps1
param(
  [string]$Region = "us-east-1",
  [string]$ArtifactsBucket = "cfn-artifacts-use1-x7p5f0",
  [string]$StackName = "genai-sumtrans",
  [string]$IngestBucket = "genai-in-use1-x7p5f0",
  [string]$OutputBucket = "genai-out-use1-x7p5f0",
  [string]$TargetLang = "fr",
  [string]$ModelId = "amazon.titan-text-lite-v1",
  [string]$Profile = "",  # optional: e.g. "genai"
  [switch]$DeleteStack
)

$profileArg = @()
if ($Profile -ne "") { $profileArg = @("--profile", $Profile) }

function Clear-Bucket {
  param([string]$BucketName)

  Write-Host "Emptying bucket $BucketName..." -ForegroundColor Yellow

  # remove all object versions and delete markers
  $keyMarker = $null
  $versionMarker = $null
  do {
    $listArgs = @(
      "s3api", "list-object-versions",
      "--bucket", $BucketName,
      "--region", $Region,
      "--output", "json"
    )
    if ($null -ne $keyMarker) { $listArgs += @("--key-marker", $keyMarker) }
    if ($null -ne $versionMarker) { $listArgs += @("--version-id-marker", $versionMarker) }
    $listArgs += $profileArg

    $raw = aws @listArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
      Write-Host "Unable to list versions for ${BucketName}: $raw" -ForegroundColor Yellow
      break
    }

    $data = $raw | ConvertFrom-Json

    foreach ($v in $data.Versions) {
      aws s3api delete-object `
        --bucket $BucketName `
        --key $v.Key `
        --version-id $v.VersionId `
        --region $Region @profileArg | Out-Null
    }

    foreach ($m in $data.DeleteMarkers) {
      aws s3api delete-object `
        --bucket $BucketName `
        --key $m.Key `
        --version-id $m.VersionId `
        --region $Region @profileArg | Out-Null
    }

    $keyMarker = $data.NextKeyMarker
    $versionMarker = $data.NextVersionIdMarker
  } while ($data.IsTruncated)

  # remove any current objects (non-versioned buckets)
  $continuation = $null
  do {
    $listObjectsArgs = @(
      "s3api", "list-objects-v2",
      "--bucket", $BucketName,
      "--region", $Region,
      "--output", "json"
    )
    if ($continuation) { $listObjectsArgs += @("--continuation-token", $continuation) }
    $listObjectsArgs += $profileArg

    $objRaw = aws @listObjectsArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
      Write-Host "Unable to list objects for ${BucketName}: $objRaw" -ForegroundColor Yellow
      break
    }

    $objData = $objRaw | ConvertFrom-Json

    foreach ($o in $objData.Contents) {
      aws s3api delete-object `
        --bucket $BucketName `
        --key $o.Key `
        --region $Region @profileArg | Out-Null
    }

    $continuation = $objData.NextContinuationToken
  } while ($objData.IsTruncated)

  # double-check with recursive rm in case of race conditions
  $rmArgs = @(
    "s3", "rm",
    "s3://$BucketName",
    "--region", $Region,
    "--recursive"
  ) + $profileArg
  aws @rmArgs | Out-Null

  Write-Host "Finished emptying $BucketName." -ForegroundColor Green
}

if ($DeleteStack) {
  Clear-Bucket -BucketName $IngestBucket
  Clear-Bucket -BucketName $OutputBucket

  Write-Host "Deleting stack $StackName..." -ForegroundColor Cyan
  aws cloudformation delete-stack `
    --stack-name $StackName `
    --region $Region @profileArg

  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

  Write-Host "Waiting for stack delete to complete..." -ForegroundColor Cyan
  aws cloudformation wait stack-delete-complete `
    --stack-name $StackName `
    --region $Region @profileArg

  if ($LASTEXITCODE -ne 0) {
    Write-Host "Stack delete reported a failure. Check CloudFormation events for details." -ForegroundColor Yellow
    exit $LASTEXITCODE
  }

  Write-Host "Stack $StackName deleted." -ForegroundColor Green
  return
}

Write-Host "Creating artifacts bucket if needed..." -ForegroundColor Cyan
aws s3 mb "s3://$ArtifactsBucket" --region $Region @profileArg 2>$null

Write-Host "Packaging CloudFormation template..." -ForegroundColor Cyan
aws cloudformation package `
  --template-file template.yaml `
  --s3-bucket $ArtifactsBucket `
  --output-template-file packaged.yaml `
  --region $Region @profileArg

Write-Host "Deploying stack $StackName..." -ForegroundColor Cyan
aws cloudformation deploy `
  --template-file packaged.yaml `
  --stack-name $StackName `
  --capabilities CAPABILITY_NAMED_IAM `
  --parameter-overrides `
    IngestBucketName=$IngestBucket `
    OutputBucketName=$OutputBucket `
    TargetLanguage=$TargetLang `
    ModelId=$ModelId `
  --region $Region @profileArg

Write-Host "Done. Stack status:" -ForegroundColor Green
aws cloudformation describe-stacks --stack-name $StackName --region $Region @profileArg `
  --query "Stacks[0].StackStatus" --output text
