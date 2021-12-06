import re

from .common import utils

from anlogger import Logger
_logger = Logger("virtualemail-gatekeeper", 'INFO')
logger = _logger.get()

from anawsutils import dynamodb
ddb = dynamodb.DDB()

from anenvconf import Config, ConfigValueType
config_schema = {
  'email_domains': {
    'type': ConfigValueType.JSON      
  },
  'ddb_tablename': {}
}

config = Config(config_schema)
email_domains = config.get_value('email_domains')
ddb_tablename = config.get_value('ddb_tablename')


def lambda_handler(event, context):
  try:
    msg = event['Records'][0]['ses']
    _recipients = msg['mail']['destination']
    
    try:
      _to = msg['mail']['destination']
    except:
      _to = '<unknown>'
      
    try:
      _from = msg['mail']['source']
    except:
      _from = '<unknown>'
      
    try:
      _subj = msg['mail']['commonHeaders']['subject']
    except:
      _subj = '<unknown>'
  
    recipients = []
    for recipient in _recipients:
      for email_domain in email_domains:
        if re.search('@{}$'.format(email_domain), recipient, re.IGNORECASE):
          recipients.append(recipient)
      
    if len(recipients) > 0:
      for recipient in recipients:
        r = ddb.get_item(ddb_tablename, 'virtualemail', recipient.lower())
      
        if r is not None:
          # Virtual address found, accept email
          logger.info("Accept message (From: {}, To: {}, Subj: {})".format(_from, _to, _subj))
          return None

    # drop email
    logger.info("Dropping message, virtual address not found (From: {}, To: {}, Subj: {})".format(_from, _to, _subj))
    return {'disposition': 'stop_rule_set'}
      
  except Exception as e:
    # Something failed, we'll notify admins and let the email pass just in case
    try:
      import json
      utils.handle_exception(logger, e, 'lambda_handler()', text=json.dumps(event))
    except Exception as e:
      # Something failed again, let's just let the email pass
      logger.error("Exception "+e)
    
  logger.info("Accept message (From: {}, To: {}, Subj: {})".format(_from, _to, _subj))
