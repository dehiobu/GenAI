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
  [switch]$DeleteStack,
  [switch]$VerboseAWS,
  [switch]$ForceRedeploy
)

$profileArg = @()
if ($Profile -ne "") { $profileArg = @("--profile", $Profile) }

$awsVerboseArg = @()
if ($VerboseAWS) { $awsVerboseArg = @("--debug") }

function Get-StackStatus {
  $status = aws cloudformation describe-stacks `
    --stack-name $StackName `
    --region $Region @profileArg `
    --query "Stacks[0].StackStatus" `
    --output text 2>$null
  return $status
}

function Clear-Bucket {
  param([string]$BucketName)
  Write-Host "Emptying bucket $BucketName..." -ForegroundColor Yellow

  $keyMarker = $null
  $versionMarker = $null
  while ($true) {
    $listArgs = @("s3api", "list-object-versions", "--bucket", $BucketName, "--region", $Region, "--output", "json")
    if ($null -ne $keyMarker) { $listArgs += @("--key-marker", $keyMarker) }
    if ($null -ne $versionMarker) { $listArgs += @("--version-id-marker", $versionMarker) }
    $listArgs += $profileArg

    $raw = aws @listArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
      Write-Host "Unable to list versions for ${BucketName}: $raw" -ForegroundColor Yellow
      break
    }

    $data = $raw | ConvertFrom-Json
    $objects = @()
    if ($data.Versions) { $objects += $data.Versions | ForEach-Object { @{ Key = $_.Key; VersionId = $_.VersionId } } }
    if ($data.DeleteMarkers) { $objects += $data.DeleteMarkers | ForEach-Object { @{ Key = $_.Key; VersionId = $_.VersionId } } }

    if ($objects.Count -gt 0) {
      $payload = @{ Objects = $objects; Quiet = $true } | ConvertTo-Json -Depth 4
      $tmpFile = New-TemporaryFile
      Set-Content -Path $tmpFile -Value $payload -Encoding utf8

      $deleteArgs = @("s3api", "delete-objects", "--bucket", $BucketName, "--region", $Region, "--delete", "file://$tmpFile") + $profileArg
      aws @deleteArgs | Out-Null
      Remove-Item $tmpFile -Force
    }

    $keyMarker = $data.NextKeyMarker
    $versionMarker = $data.NextVersionIdMarker
    if (-not $data.IsTruncated) { break }
  }

  $continuation = $null
  while ($true) {
    $listObjectsArgs = @("s3api", "list-objects-v2", "--bucket", $BucketName, "--region", $Region, "--output", "json")
    if ($continuation) { $listObjectsArgs += @("--continuation-token", $continuation) }
    $listObjectsArgs += $profileArg

    $objRaw = aws @listObjectsArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
      Write-Host "Unable to list objects for ${BucketName}: $objRaw" -ForegroundColor Yellow
      break
    }

    $objData = $objRaw | ConvertFrom-Json
    if ($objData.Contents) {
      $payload = @{ Objects = ($objData.Contents | ForEach-Object { @{ Key = $_.Key } }); Quiet = $true } | ConvertTo-Json -Depth 4
      $tmpFile = New-TemporaryFile
      Set-Content -Path $tmpFile -Value $payload -Encoding utf8

      $deleteArgs = @("s3api", "delete-objects", "--bucket", $BucketName, "--region", $Region, "--delete", "file://$tmpFile") + $profileArg
      aws @deleteArgs | Out-Null
      Remove-Item $tmpFile -Force
    }

    if (-not $objData.IsTruncated) { break }
    $continuation = $objData.NextContinuationToken
  }

  $rmArgs = @("s3", "rm", "s3://$BucketName", "--region", $Region, "--recursive") + $profileArg
  aws @rmArgs | Out-Null

  Write-Host "Finished emptying $BucketName." -ForegroundColor Green
}

if ($DeleteStack) {
  Clear-Bucket -BucketName $IngestBucket
  Clear-Bucket -BucketName $OutputBucket

  Write-Host "Deleting stack $StackName..." -ForegroundColor Cyan
  aws cloudformation delete-stack --stack-name $StackName --region $Region @profileArg
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

  Write-Host "Waiting for stack delete to complete..." -ForegroundColor Cyan
  aws cloudformation wait stack-delete-complete --stack-name $StackName --region $Region @profileArg
  if ($LASTEXITCODE -ne 0) {
    Write-Host "Stack delete reported a failure. Check CloudFormation events for details." -ForegroundColor Yellow
    exit $LASTEXITCODE
  }

  Write-Host "Stack $StackName deleted." -ForegroundColor Green
  return
}

if ($ForceRedeploy) {
  $status = Get-StackStatus
  if ($status -eq "ROLLBACK_COMPLETE" -or $status -eq "DELETE_FAILED") {
    Write-Host "Stack $StackName is in terminal state ($status). Attempting cleanup..." -ForegroundColor Yellow
    Clear-Bucket -BucketName $IngestBucket
    Clear-Bucket -BucketName $OutputBucket

    aws cloudformation delete-stack --stack-name $StackName --region $Region @profileArg
    Write-Host "Waiting for stack delete to complete..." -ForegroundColor Cyan
    aws cloudformation wait stack-delete-complete --stack-name $StackName --region $Region @profileArg
    if ($LASTEXITCODE -ne 0) {
      Write-Host "Stack deletion failed. Check CloudFormation events." -ForegroundColor Red
      exit $LASTEXITCODE
    }

    Write-Host "Stack $StackName deleted. Proceeding with redeploy..." -ForegroundColor Green
  }
}

Write-Host "Creating artifacts bucket if needed..." -ForegroundColor Cyan
aws s3 mb "s3://$ArtifactsBucket" --region $Region @profileArg 2>$null

Write-Host "Packaging CloudFormation template..." -ForegroundColor Cyan
aws cloudformation package `
  --template-file template.yaml `
  --s3-bucket $ArtifactsBucket `
  --output-template-file packaged.yaml `
  --region $Region @profileArg @awsVerboseArg

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
  --region $Region @profileArg @awsVerboseArg

Write-Host "Done. Stack status:" -ForegroundColor Green
aws cloudformation describe-stacks --stack-name $StackName --region $Region @profileArg `
  --query "Stacks[0].StackStatus" --output text