# Virtualmail

Virtualmail is an API managed virtual email forwarding solution. It is most useful for automating account delivery for AWS Organizations, where you need a unique email address for each account. Virtualmail allows you to manage the virtual email addresses and their recipients thru a simple API.

Any email sent to the virtual email address will be forwarded to the recipients and optionally also to a centralized admin account. The sender address will be the virtual email address and the original sender can be found from the email header `X-Virtualmail-Original-From`. 


## Deployment with integrated build pipeline

If you have your own CI pipeline and can push OCI Containers to ECR, you can select not to deploy the build pipeline. Otherwise you want to deploy the solution following these instructions.

1. Get an AWS account, possibly one that is dedicated for this use, but most preferrably one that is not using SES for anything else.
1. Select a region for your Virtuamail deployment that is supported for SES email reception. [See AWS documentation](https://docs.aws.amazon.com/ses/latest/dg/regions.html#region-receive-email)
1. Deploy CloudFormation-stack `virtualmail-ci.yaml` with defaults. 
1. Check the outputs for the deployed stack and copy the address for the `CodeCommitRepository`.  
1. Push the Virtualmail repository code fully into the CodeCommit repository shown in the stack output (see instructions below).
1. Check your CodePipline for a successful Virtualmail build. If the build is still running, wait until it is succesfully finished.
1. Deploy CloudFormation stack `virtualmail.yaml`. See configurable parameteters below.
1. Go to `SES console > Email Receiving` and enable the Virtualmail RuleSet (Set As Active).
1. In the `SES Console > Verified identities`, add verified domain identities for all the domains your Virtualmail app is configured to handle.
1. Request production access for your SES use case. Ensure that your use case is conforming with AWS policies.
    1. If you are only evaluating this solution, you can alternatively verify all the email recipients you will test with at the Verified identities page.
    1. Depending on your sending/receiving volume, you will likelly need to request an increase to the sending limits. 
1. Set MX-records for all your domain towards the SES inbound address in your region, for example `inbound-smtp.eu-west-1.amazonaws.com`. [See AWS documentation](https://docs.aws.amazon.com/ses/latest/dg/receiving-email-mx-record.html) 
1. Optional: Go to CloudWatch Logs and set expiration to a desired age (for example 30d) for each Virtualmail Lambda Function log group to ensure old logs are removed automatically.
1. Optional: Subscribe to the `Virtualmail-AdminMessages` SNS-topic to receive notifications on Virtualmail runtime errors.


### Pushing code to the Codecommit repository

The following steps are intended to be executed in CloudShell. If you wish, you can also adapt these commands and run them on any other environment. 

If you choose to run these commands from somewhere else, you will need `awscli` and `git-remote-codecommit` on your client:

```
python3 -m pip install awscli git-remote-codecommit
```

To commit the code, follow these steps:
```
git clone https://.... virtualmail
cd virtualmail
git remote add aws <ci-stack-output-CodeCommitRepository>
git push aws
```

### Updating Virtualmail app for an existing installation 

1. Checkout the version you want to update to from git.
1. Push the new version to the CodeCommit repository.
1. Wait until the container image build is finished.
1. Check the ECR console for the build-tag of the latest uploaded container image in the Virtualmail repository, and copy it.
1. Go to the Virtualmail CloudFormation stack and update it. Set `ContainerVersion` to the tag you copied. Update the stack.


## Deployment with existing build pipeline

1. Get an AWS account, possibly one that is dedicated for this use, but most preferrably one that is not using SES for anything else.
1. Select a region for your Virtuamail deployment.
1. Deploy CloudFormation stack `virtualmail-ci.yaml` with `DeployBuildPipeline=false`.
1. Check the outputs for the deployed stack and copy the ECR repository address from `EcrRepositoryAddress`.  
1. Build the Virtualmail app container and push the image to the ECR repository. Get the image tag for the deployed image.
1. Deploy CloudFormation stack `virtualmail.yaml`. Give the image tag as the ContainerVersion tag. See configurable parameteters below.
1. Follow the `Deployment with integrated build pipeline` guide from right after deployment of the `virtualmail.yaml` stack.

## Configuration parameters

Virtualmail is configured via the Cloudformation template parameters. You may modify these options any time by altering the stack parameters. It is good practice to check Virtualmail logs from CloudWatch Logs and send a test email after making changes to ensure that the changes are valid and that everything works perfectly. 

Here is a table of the configuration options:

|Parameter|Type|Example|Description|
|---|---|---|---|
|BouncesEmail|json object string|`{ "%": "bounces@example.com", "other.example.com": "bounces-other@example.com" }`|REQUIRED. The address for each virtualmail domain where bounces are directed to. You must specify a '%'-key to catch domains that are not specifically defined.|
|DefaultSender|json object string|`{ "%": "sender@example.com", "other.example.com": "sender-other@example.com" }`|REQUIRED. The address for each virtualmail domain's default sender address. You must specify a '%'-key to catch domains that are not specifically defined.||
|EmailFilter|json array string|`[ "@blocked.example.com$" ]`|Array of regex-strings. If any regex is matched to any email recipient, no actual email will be sent to that address.|
|MasterEmail|json object string|`{ "%": null, "example.com": admin-team@example.com }`|Address where to send a carbon copy of each mail for a specific virtual domain. Specify a '%'-key to catch domains that are not specifically defined. You can use `null` as the value if you do not want a copy of each mail.|
OwnerDomains|json array string|`[ "example.com" ]`|An array of email domains. This array is used to ensure that only allowed domains are entered as owners of virtualmail addresses.|
RecipientDomains|json array string|`[ "example.com" ]`|An array of email domains. This array is used to ensure that only allowed domains are entered as recipients of virtualmail addresses.|
RestrictedAccesskeys|json object string|`{ "ov6qm1nxlk": "other.example.com }`|This restricts a specific API Gateway api key to managing only virtualmail addresses with a specific domain. If a properly configured api key is not listed here, it will have unrestricted editing ability.|
VirtualmailDomains|comma delimited list|`example.com, other.example.com, another.example.com`|These are the configured virtualmail domains that can be used for virtualmail addresses.|


## Injecting mail

Sometimes it is necessary to send events or notifications from your own sources to the accounts in your Virtualmail directory. Virtualmail provides a convenient way to send these messages by allowing you to inject json-formatted messages via an SQS queue. 

The format is the following:

```json
{
    "to": "recipient@example.com",
    "from": "sender@example.com",
    "subject": "Email subject",
    "body": "This is the body of the mail",
    "headers": { 
        "X-MY-HEADER": "my-header-value",
        "X-MY-OTHER-HEADER": "my-other-header-value" 
    }
}
```

Of these properties, `headers` is optional while the others are mandatory.

You can find out the inject queue's arn and url from the `virtualmail.yaml` CloudFormation stack's outputs. Keep in mind that you will need to give your sending resources permissions to the queue. You can utilize IAM policies or the queue's Queue Policy for this, depending on your use case.

If you wish, you may use the cloudformation template parameter `InjectorAwsPrincipalArns` to give a comma separaetd list of principal arns that will be allowed to inject mail to the queue. For example `arn:aws:iam::123456789012:root` would allow account id 123456789012 to put messages into the queue.


## Using the API

Openapi 3 documentation for the API can be found from `openapi.yaml`.

You can find the API endpoint address form the virtualmail cloudformation stack outputs.

Retrieve the API key from the API Gateway console.
