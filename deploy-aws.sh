#!/bin/bash

# This script deploys the Discord bot to AWS Fargate.

# --- Configuration ---
# The following variables will be used to configure the deployment.
# You can either set them here or as environment variables.

# AWS Region
AWS_REGION=${AWS_REGION:-"us-east-1"}

# The name of the ECR repository
ECR_REPO_NAME=${ECR_REPO_NAME:-"lotslarp-discord-bot"}

# The name of the ECS cluster
ECS_CLUSTER_NAME=${ECS_CLUSTER_NAME:-"lotslarp-discord-bot-cluster"}

# The name of the ECS service
ECS_SERVICE_NAME=${ECS_SERVICE_NAME:-"lotslarp-discord-bot-service"}

# The name of the ECS task family
ECS_TASK_FAMILY=${ECS_TASK_FAMILY:-"lotslarp-discord-bot-task"}

# The name for the secrets prefix in AWS Secrets Manager
SECRETS_PREFIX=${SECRETS_PREFIX:-"LOTSLARP_DISCORD_BOT"}

# --- Script ---

set -e

echo "--- Configuration ---"
echo "AWS Region: $AWS_REGION"
echo "ECR Repo Name: $ECR_REPO_NAME"
echo "ECS Cluster Name: $ECS_CLUSTER_NAME"
echo "ECS Service Name: $ECS_SERVICE_NAME"
echo "ECS Task Family: $ECS_TASK_FAMILY"
echo "Secrets Prefix: $SECRETS_PREFIX"
echo "--------------------"

echo ""
echo "This script will deploy the Discord bot to AWS Fargate."
echo "Please make sure you have the following tools installed:"
echo "- aws-cli"
echo "- docker"
echo "- jq"
echo ""
echo "And that you are authenticated with AWS CLI."
echo ""

if [ ! -f .env.aws ]; then
    echo ".env.aws file not found. Please copy .env.aws.example to .env.aws and fill in your secrets."
    exit 1
fi

# Get AWS Account ID
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query "Account" --output text)
echo "Using AWS Account ID: $AWS_ACCOUNT_ID"

# Create/update secrets in AWS Secrets Manager
echo "Creating/updating secrets in AWS Secrets Manager..."
SECRET_ARNS_JSON="[]"
while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ "$line" =~ ^\s*# || -z "$line" ]]; then
        continue
    fi
    key=$(echo "$line" | cut -d '=' -f 1)
    value=$(echo "$line" | cut -d '=' -f 2-)
    secret_name="${SECRETS_PREFIX}_${key}"

    # Check if secret exists
    if aws secretsmanager describe-secret --secret-id "$secret_name" --region "$AWS_REGION" &> /dev/null; then
        echo "Updating secret: $secret_name"
        aws secretsmanager put-secret-value --secret-id "$secret_name" --secret-string "$value" --region "$AWS_REGION"
    else
        echo "Creating secret: $secret_name"
        aws secretsmanager create-secret --name "$secret_name" --secret-string "$value" --region "$AWS_REGION"
    fi
    SECRET_ARN=$(aws secretsmanager describe-secret --secret-id "$secret_name" --query "ARN" --output text --region "$AWS_REGION")
    SECRET_ARNS_JSON=$(echo "$SECRET_ARNS_JSON" | jq --arg key "$key" --arg arn "$SECRET_ARN" '. + [{name: $key, valueFrom: $arn}]')
done < .env.aws

# Create ECR repository if it doesn't exist
echo "Checking for ECR repository: $ECR_REPO_NAME"
if ! aws ecr describe-repositories --repository-names "$ECR_REPO_NAME" --region "$AWS_REGION" &> /dev/null; then
    echo "Creating ECR repository: $ECR_REPO_NAME"
    aws ecr create-repository --repository-name "$ECR_REPO_NAME" --region "$AWS_REGION"
fi

# Login to ECR
echo "Logging in to ECR..."
aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

# Build and push the Docker image
echo "Building and pushing Docker image..."
IMAGE_TAG="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPO_NAME:latest"
docker build -t "$IMAGE_TAG" .
docker push "$IMAGE_TAG"
echo "Image pushed to $IMAGE_TAG"

# Create ECS cluster if it doesn't exist
echo "Checking for ECS cluster: $ECS_CLUSTER_NAME"
if ! aws ecs describe-clusters --clusters "$ECS_CLUSTER_NAME" --region "$AWS_REGION" | grep -q "$ECS_CLUSTER_NAME"; then
    echo "Creating ECS cluster: $ECS_CLUSTER_NAME"
    aws ecs create-cluster --cluster-name "$ECS_CLUSTER_NAME" --region "$AWS_REGION"
fi

# Create a log group for the task
LOG_GROUP_NAME="/ecs/$ECS_TASK_FAMILY"
echo "Checking for CloudWatch log group: $LOG_GROUP_NAME"
if ! aws logs describe-log-groups --log-group-name-prefix "$LOG_GROUP_NAME" --region "$AWS_REGION" | grep -q "$LOG_GROUP_NAME"; then
    echo "Creating CloudWatch log group: $LOG_GROUP_NAME"
    aws logs create-log-group --log-group-name "$LOG_GROUP_NAME" --region "$AWS_REGION"
fi


# Define the ECS task
echo "Defining ECS task..."
TASK_DEFINITION=$(cat <<EOF
{
    "family": "$ECS_TASK_FAMILY",
    "networkMode": "awsvpc",
    "containerDefinitions": [
        {
            "name": "$ECS_SERVICE_NAME",
            "image": "$IMAGE_TAG",
            "portMappings": [
                {
                    "containerPort": 8080,
                    "hostPort": 8080
                }
            ],
            "logConfiguration": {
                "logDriver": "awslogs",
                "options": {
                    "awslogs-group": "$LOG_GROUP_NAME",
                    "awslogs-region": "$AWS_REGION",
                    "awslogs-stream-prefix": "ecs"
                }
            },
            "secrets": $SECRET_ARNS_JSON
        }
    ],
    "requiresCompatibilities": [
        "FARGATE"
    ],
    "cpu": "256",
    "memory": "512"
}
EOF
)

# Register the ECS task definition
echo "Registering ECS task definition..."
TASK_DEFINITION_ARN=$(aws ecs register-task-definition --cli-input-json "$TASK_DEFINITION" --region "$AWS_REGION" --query "taskDefinition.taskDefinitionArn" --output text)
echo "Task definition registered: $TASK_DEFINITION_ARN"

# Create or update the ECS service
echo "Checking for ECS service: $ECS_SERVICE_NAME"
if ! aws ecs describe-services --cluster "$ECS_CLUSTER_NAME" --services "$ECS_SERVICE_NAME" --region "$AWS_REGION" | grep -q "$ECS_SERVICE_NAME"; then
    echo "Creating ECS service: $ECS_SERVICE_NAME"
    aws ecs create-service \
        --cluster "$ECS_CLUSTER_NAME" \
        --service-name "$ECS_SERVICE_NAME" \
        --task-definition "$TASK_DEFINITION_ARN" \
        --desired-count 1 \
        --launch-type "FARGATE" \
        --network-configuration "awsvpcConfiguration={subnets=[],securityGroups=[]}" \
        --region "$AWS_REGION"
    echo "Service created. You need to configure the subnets and security groups in the AWS console."
else
    echo "Updating ECS service: $ECS_SERVICE_NAME"
    aws ecs update-service \
        --cluster "$ECS_CLUSTER_NAME" \
        --service "$ECS_SERVICE_NAME" \
        --task-definition "$TASK_DEFINITION_ARN" \
        --desired-count 1 \
        --region "$AWS_REGION"
    echo "Service updated."
fi

echo "Deployment to AWS Fargate initiated."
echo "NOTE: If this is the first deployment, you must configure the service's VPC, subnets, and security groups in the AWS ECS console to allow traffic to port 8080."
