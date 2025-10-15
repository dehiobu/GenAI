terraform {
  required_providers { aws = { source = "hashicorp/aws" } }
}

provider "aws" {
  region = "us-east-1"
}

variable "ingest_bucket"  { default = "genai-in-use1-x7p5f0" }
variable "output_bucket"  { default = "genai-out-use1-x7p5f0" }
variable "model_id"       { default = "anthropic.claude-3-haiku-20240307-v1:0" }
variable "target_lang"    { default = "fr" }

data "aws_caller_identity" "me" {} 

data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/src"
  output_path = "${path.module}/lambda.zip"
}

resource "aws_s3_bucket" "ingest" {
  bucket = var.ingest_bucket
}

resource "aws_s3_bucket" "out" {
  bucket = var.output_bucket
}

resource "aws_iam_role" "lambda_role" {
  name = "summarise-translate-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{ Effect="Allow", Principal={ Service="lambda.amazonaws.com" }, Action="sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy" "lambda_policy" {
  name = "summarise-translate-inline"
  role = aws_iam_role.lambda_role.id
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Action = ["logs:CreateLogGroup","logs:CreateLogStream","logs:PutLogEvents"],
        Resource = "*"
      },
      {
        Effect="Allow",
        Action=["s3:GetObject","s3:GetObjectAttributes"],
        Resource="arn:aws:s3:::genai-in-use1-x7p5f0/*"
      },
      {
        Effect="Allow",
        Action=["s3:PutObject"],
        Resource="arn:aws:s3:::genai-out-use1-x7p5f0/*"
      },
      {
        Effect="Allow",
        Action=["bedrock:InvokeModel"],
        Resource="arn:aws:bedrock:us-east-1::foundation-model/*"
      },
      {
        Effect="Allow",
        Action=["translate:TranslateText"],
        Resource="*"
      }
    ]
  })
}

resource "aws_lambda_function" "fn" {
  function_name = "summarise-translate"
  role          = aws_iam_role.lambda_role.arn
  runtime       = "python3.11"
  handler       = "app.lambda_handler"
  filename      = data.archive_file.lambda_zip.output_path
  memory_size   = 1024
  timeout       = 120
  reserved_concurrent_executions = 5
  environment {
    variables = {
      OUTPUT_BUCKET      = var.output_bucket
      SUMMARY_PREFIX     = "summaries/"
      TRANSLATION_PREFIX = "translations/"
      TARGET_LANG        = var.target_lang
      MODEL_ID           = var.model_id
      MAX_BYTES          = "500000"
    }
  }
}

resource "aws_lambda_permission" "allow_s3_invoke" {
  statement_id  = "AllowExecutionFromS3"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fn.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.ingest.arn
}

resource "aws_s3_bucket_notification" "ingest_notifications" {
  bucket = aws_s3_bucket.ingest.id
  lambda_function {
    lambda_function_arn = aws_lambda_function.fn.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "incoming/"
    filter_suffix       = ".txt"
  }
  depends_on = [aws_lambda_permission.allow_s3_invoke]
}
