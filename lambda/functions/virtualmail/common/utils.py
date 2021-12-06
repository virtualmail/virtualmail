import os
from anawsutils.sns import SNS

sns = SNS()
sns_arn =  os.environ["sns_admin"] if "sns_admin" in os.environ else None


def send_admin_sns(logger, subject, message):
  if sns_arn is None:
    logger.error("Environment variable sns_admin is not set")
    
  else:
    response = sns.send_sns(sns_arn, subject, message)
    return response


def handle_exception(logger, e, when=None, text=None, stop_processing=False):
  import traceback
  s = 'Exception "{}"{}:\n{}\n{}'.format(
    e, 
    (" while " + when) if when is not None else "", 
    '-'*60, 
    traceback.format_exc()
  )
  if text is not None:
    s += '\n\n' + text

  logger.error(s)

  try:
    send_admin_sns(logger, "Virtualmail exception", s)
  except Exception as e:
    logger.error("Exception while sending admin message: "+str(e))

  if stop_processing == True:
    raise e
  