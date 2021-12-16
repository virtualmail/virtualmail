import boto3
import json
import re

from datetime import datetime

from .common import utils
from .common.exceptions import PassthroughException

from anlogger import Logger
_logger = Logger("virtualmail-handler", 'INFO')
logger = _logger.get()

from anawsutils import dynamodb
ddb = dynamodb.DDB()

from anenvconf import Config, ConfigValueType
config_schema = {
    'bounces_email': {
        'type': ConfigValueType.JSON,
        'required_key': '%'
    },
    'default_sender': {
        'type': ConfigValueType.JSON,
        'required_key': '%'
    },
    'email_domains': {
        'type': ConfigValueType.JSON      
    },
    'ddb_tablename': {},
    'ddb_tablename_log': {},
    'sns_admin': {},
    'master_email': {
        'type': ConfigValueType.JSON,
        'default': '{ "%": null }'
    },
    'email_filter': {
        'type': ConfigValueType.JSON,
        'default': "[]"
    },
    'print_mail_info': {
        'type': ConfigValueType.BOOL,
        'default': True
    }
}

config = Config(config_schema)


def send_raw_email(raw):
  ses = boto3.client('ses')
  response = ses.send_raw_email(RawMessage={ 'Data': raw })
  return response


def get_email_from_s3(bucket, key):
  s3  = boto3.client('s3')
  obj = s3.get_object(Bucket=bucket, Key=key)
  return obj['Body'].read().decode()

  
def reconstruct_email(text, sender, recipients, returnpath, headers = {}):
  t = text.split("\n")
  result = []
  result.append('From: '+sender)
  result.append('To: ' + ', '.join(recipients))
  
  if returnpath is None:
    raise Exception("Returnpath is none")

  if sender != returnpath:
    result.append('Return-Path: '+returnpath)
    
  for k, v in headers.items():
    result.append("{}: {}".format(k, v))

  i = 0
  for s in t:
    i += 1
    if (re.match('Subject:', s, re.IGNORECASE) or
        re.match('Content-Transfer-Encoding:', s, re.IGNORECASE) or
        re.match('MIME-Version:', s, re.IGNORECASE)):
      result.append(s.rstrip())
    elif re.match('Content-Type:', s, re.IGNORECASE):
      result.append(s.rstrip())
      for _s in t[i:]:
        if re.match(r'^\s', _s):
          result.append(_s.rstrip())
        else:
          break
    elif len(s.strip()) == 0:
      result.append('')
      break

  for s in t[i:]:
    result.append(s)
    
  return '\n'.join(result)


def get_value_for_domain(d, dest_domain):
  if not isinstance(d, dict):
    return None
  
  if dest_domain is not None and dest_domain in d.keys():
    return d[dest_domain]
  else:
    if '%' in d:
      return d['%']
      
  return None
  

def log_to_ddb(email_date, sender, recipients, subject, s3key, s3bucket, messageid=None):           

  if s3key is None or s3bucket is None:
    _id = messageid
    _path = None
  else:
    _id = s3key.split('/')[-1]
    _path = '{}/{}'.format(s3bucket, '/'.join(s3key.split('/')[:-1])) 

  item = { 
    'id':          _id,
    'email_date':  email_date,
    'rcvd_date':   datetime.now().isoformat(),
    'sender':      sender,
    'recipients':  json.dumps(recipients),
    'subject':     subject
  }

  if _path is not None:
    item['s3_location'] = _path
  
  try:
    ddb.put_item(config.get_value('ddb_tablename_log'), item)
  except Exception as e:
    raise PassthroughException(e, '_ddb_put_item()', text=json.dumps(item))


def listsafe_str(o):
  return ', '.join(o) if isinstance(o, list) else str(o)

##############################################################################  

def handle_event(event):
  print(json.dumps(event))

  for _event in event['Records']:
    eventsource = None
    for x in ['EventSource', 'eventSource']:
      if x in _event:
        eventsource = _event[x]
        break
      
    if eventsource == 'aws:sqs':
      _msg = _event['body']
    elif eventsource == 'aws:sns':
      _msg = _event['Sns']['Message']   
      
    try:
      msg  = json.loads(_msg)
    except Exception as e:
      utils.handle_exception(
        e, 
        'converting event body to json',
        text=json.dumps(_event, indent=4)
      )
      continue

    headers = {}

    try:
      if eventsource == 'aws:sqs':
        for x in ['subject', 'to', 'from', 'body']:
          if x not in msg:
            print("Item {} missing from sqs json".format(x))
            continue
        
        mail_subject    = msg['subject']
        mail_recipients = { 'to': msg['to'] } 
        mail_from       = msg['from']
        mail_date       = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")
        s3key           = None
        s3bucket        = None
        messageid       = _event["messageId"]
        destinations    = [ msg['to'] ]
        email_body      = "\n" + msg['body']
        
        _headers        = msg["headers"] if "headers" in msg else None
        
        headers["Subject"] = mail_subject
        headers["Date"]    = mail_date
      
        if isinstance(_headers, dict):
          for k, v in _headers.items():
            if k.lower() in ['to', 'from', 'subject']:
              continue
            headers[k] = v
        
      elif eventsource == 'aws:sns':

        mail_subject    = msg['mail']['commonHeaders']['subject']
        mail_recipients = { 'to': msg['mail']['commonHeaders']['to'] } 
        mail_from       = msg['mail']['commonHeaders']['from'][0]
        mail_date       = msg['mail']['commonHeaders']['date']
        s3key           = msg['receipt']['action']['objectKey']
        s3bucket        = msg['receipt']['action']['bucketName']
        messageid       = msg['mail']['messageId']
        destinations    = msg['mail']['destination']
        email_body      = None
        
    except Exception as e:
      utils.handle_exception(
        e,
        'processing mail parameters',
        text=json.dumps(_event, indent=4)
      )
      continue
  

    if (
      'mail' in msg and 
      'messageId' in msg['mail'] and 
      msg['mail']['messageId'] == 'AMAZON_SES_SETUP_NOTIFICATION'
    ):
      # These messages do not need to be processed
      continue
  
    dest_domain = None
    vmail = None

    for dest in destinations:
      try:
        dest_domain = dest.split('@')[1]
        if dest_domain in config.get_value("email_domains"):
          vmail = dest
        else:
          # not our domain -> skip
          continue
      
        if vmail is None:
          vmail = get_value_for_domain(
            config.get_value("default_sender"), 
            dest_domain
        )

        if config.get_value("print_mail_info") is True:
          logger.info("{dash} New email {dash}".format(dash="-"*30))
          logger.info("From:    " + mail_from)
          logger.info("To:      " + vmail)
          logger.info("Date:    " + mail_date)
          logger.info("Subject: " + mail_subject)
          logger.info("Vmail:   " + vmail)
          logger.info("Msg:     s3://{}/{}".format(s3bucket, s3key))

      except Exception as e:
        utils.handle_exception(
          logger,
          e, 
          'looking for destination and s3 values from message'
        )
        continue
      
      try:
        log_to_ddb(
          mail_date, 
          mail_from, 
          mail_recipients, 
          mail_subject, 
          s3key, 
          s3bucket,
          messageid
        )
      except PassthroughException as e:
        t = e.text + "\n\n" + _msg if e.text is not None else _msg
        utils.handle_exception(logger, e.e, e.when, text=t)
      except Exception as e:
        utils.handle_exception(logger, e, 'log inbound email to log ddb', text=_msg)
          
      if s3bucket is not None and s3key is not None:
        try:
          t = get_email_from_s3(s3bucket, s3key)
        except Exception as e:
          utils.handle_exception(e, 'retrieving email from s3', text=_msg)
          continue
      else:
        t = email_body

      efilters = config.get_value("email_filter")
      recipients = []
      try:
        item = ddb.get_item(
          config.get_value('ddb_tablename'),
          'virtualemail',
          vmail.lower()
        )
        if item is not None:
          if (
            re.search("password-reset-noreply@aws.amazon.com", 
            mail_from, 
            re.IGNORECASE
          ) and ('managed' not in item or item['managed'] != False)):
            # for a mananged account, a password reset email is not allowed to 
            # pass through to recipients; being non-managed must be explicit
            pass
          else:
            j = json.loads(item['recipients'])

            for rec in j:
              filter_out = False
              
              # Filter out email eddresses that we don't want to actually 
              # send any email (for example test domains, etc.)
              for efilter in efilters:
                if re.search(efilter, rec):
                  filter_out = True
                  break
                
              # Check if the email address belongs to one of our managed domains
              # and if it does, that the vmail actually exists
              if filter_out is False:
                recdom = rec.split('@')[1]

                if recdom in config.get_value("email_domains"):
                  item = ddb.get_item(
                    config.get_value('ddb_tablename'),
                    'virtualemail',
                    rec.lower()
                  )

                  if item is None:
                    # Not found so we'll block this address out to make sure
                    # there are no bounces
                    filter_out = True
                    _s = "Recipient {} is in one of our virtualmail domains but " \
                        "such vmail address does not exist"
                    logger.info(_s.format(rec))
                
              if filter_out is False and rec not in recipients:
                recipients.append(rec)

              elif filter_out is True:
                logger.info("Recipient {} filtered out".format(rec))
                
      except Exception as e:
        utils.handle_exception(
          logger,
          e,
          'doing ddb lookup for virtualemail',
          text=_msg
        )
        continue
      
      master_email = get_value_for_domain(
        config.get_value("master_email"), 
        dest_domain
      )
      
      if (master_email is not None and master_email not in recipients):
        recipients.append(master_email)
      
      if config.get_value("print_mail_info") is True:
        logger.info("Recipients: " + listsafe_str(recipients))    
      
      bounces_email = get_value_for_domain(
        config.get_value("bounces_email"), 
        dest_domain
      )    

      headers["X-Virtualmail-Original-From"] = mail_from 
      if messageid is not None:
        headers["X-Virtualmail-Id"] = messageid
      
      try:
        raw = reconstruct_email(t, vmail, recipients, bounces_email, headers)
      except Exception as e:
        utils.handle_exception(logger, e, 'reconstructing email', text=_msg)
        continue
      
      try:
        if len(recipients) > 0:
          send_raw_email(raw)
        else:
          logger.info("No recipients, no email!")
      except Exception as e:
        utils.handle_exception(logger, e, 'sending email', text=_msg)
        continue


def lambda_handler(event, context):
  try:
    handle_event(event)
  except Exception as e:
    utils.handle_exception(logger, e, 'handle_event', text=json.dumps(event))