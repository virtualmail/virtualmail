from .vmapi.actions import Actions

from anslapi import APIHandler
from anlogger import Logger
_logger = Logger("virtualmail-api", 'INFO')
logger = _logger.get()

from anenvconf import Config, ConfigValueType
config_schema = {
  'email_domains': {
    'type': ConfigValueType.JSON      
  },
  'ddb_tablename': {},
  'sns_admin': {},
  'owner_domains': {
    'type': ConfigValueType.JSON
  },
  'recipient_domains': {
    'type': ConfigValueType.JSON
  },
  'restricted_access_keys': {
    'type': ConfigValueType.JSON,
    'default': '{}'
  }
}

config = Config(config_schema)


def lambda_handler(event, context):
  
  apikeyid = event['requestContext']['identity']['apiKeyId']
  logger.info("apikeyid={}".format(apikeyid))

  ah = APIHandler()
  ac = Actions(config, apikeyid, logger)
  
  ah.add_handler('/get',    'POST', ac.get)
  ah.add_handler('/add',    'POST', ac.add)
  ah.add_handler('/delete', 'POST', ac.delete)
  ah.add_handler('/modify', 'POST', ac.modify)
  
  response = ah.handle(event)
    
  logger.info(response) 
  return response
