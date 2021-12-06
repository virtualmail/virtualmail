import json
from anlogger import Logger
logger_obj = Logger(name="virtualmail", default_loglevel="INFO", fmt=None, syslog=None)
logger = logger_obj.get()

def lambda_handler(event, context):
  logger.warn("Default handler in virtualmail app container called - please configure Lambda to call the correct handler!")
  logger.info(json.dumps(event))


# docker run --rm -p 9001:8080 -e AWS_ACCESS_KEY_ID=redacted -e AWS_SECRET_ACCESS_KEY=redacted -e AWS_REGION=eu-central-1  virtualmail:latest virtualmail.default.lambda_handler
# curl -XPOST "http://localhost:9001/2015-03-31/functions/function/invocations" -d "@sample.txt"
