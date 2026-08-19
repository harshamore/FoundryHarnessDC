resource "aws_iam_role" "lambda_exec" {
  name               = "lambda-exec-role"
  assume_role_policy = "{\"Version\": \"2012-10-17\", \"Statement\": [{\"Effect\": \"Allow\", \"Principal\": {\"Service\": \"lambda.amazonaws.com\"}, \"Action\": \"sts:AssumeRole\"}]}"
}

resource "aws_iam_role_policy" "lambda_exec_inline" {
  name = "lambda-exec-inline-policy"
  role = aws_iam_role.lambda_exec.id
  policy = <<-POLICY
    {
      "Version": "2012-10-17",
      "Statement": [
        {
          "Effect": "Allow",
          "Action": ["s3:*", "dynamodb:*"],
          "Resource": ["arn:aws:s3:::prod-*", "arn:aws:dynamodb:*:*:table/prod-*"]
        }
      ]
    }
  POLICY
}

resource "aws_lambda_function" "process_upload" {
  function_name = "process-upload"
  role          = aws_iam_role.lambda_exec.arn
  handler       = "handler.handler"
  runtime       = "python3.12"
  source_dir    = "./lambda"
}

resource "aws_s3_bucket" "uploads" {
  bucket = "cloud-toy-target-uploads"
}

resource "aws_s3_bucket_public_access_block" "uploads" {
  bucket                  = aws_s3_bucket.uploads.id
  block_public_acls       = false
  block_public_policy     = false
  ignore_public_acls      = false
  restrict_public_buckets = false
}
