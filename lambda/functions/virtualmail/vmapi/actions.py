import json
import re

from anawsutils import dynamodb
from anenvconf import Config
from anlogger import Logger

ddb = dynamodb.DDB()

from ..common import utils


class Actions(object):
  def __init__(self, config: Config, apikeyid, logger: Logger):
    self.config   = config
    self.apikeyid = apikeyid
    self.logger   = logger
    
    self.ddb_tablename = config.get_value("ddb_tablename")
    self.email_domains = config.get_value("email_domains")
    self.owner_domains = config.get_value("owner_domains")
    self.recipient_domains = config.get_value("recipient_domains")
    

  def handle_exception(self, e, when=None, text=None, stop_processing=False):
    utils.handle_exception(self.logger, e, when, text, stop_processing)


  @staticmethod
  def validate_email(email_address):
    rex = re.match(
      r"^[a-zA-Z0-9][a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]*[a-zA-Z0-9]{2,}$", 
      email_address,
      re.IGNORECASE)
    return rex is not None
    

  def _get_data(self, event):
    return json.loads(event['body']) if 'body' in event else None


  def validate_key_access(self, virtualemail_address):
    x = virtualemail_address.split('@')
    if len(x) != 2 or x[1].lower() not in self.email_domains:
      return False
      
    vmail_domain = x[1].lower()
    
    rak = self.config.get_value("restricted_access_keys")
    if self.apikeyid not in rak.keys():
      return True
    
    if vmail_domain in rak[self.apikeyid]:
      return True
    else:  
      return False


  @staticmethod
  def _require_params(params, data, action):
    for param in params:
      if param not in data:
        result = {
          "status":  "FAIL",
          "action":  action,
          "message": "Request missing parameter '{}'".format(param)
        }
        return (400, result)
        
      if data[param] is None or len(data[param]) == 0:
        result = {
          "status":  "FAIL",
          "action":  action,
          "message": "Invalid value for parameter '{}'".format(param)
        }
        return (400, result)        

    return None


  def _action_add_or_modify(self, event, action):
    data   = self._get_data(event)

    modify = (action == 'modify')

    if modify is True:
      required_params = ['virtualemail']
    else:
      required_params = ['virtualemail', 'recipients', 'owner']
    
    r = self._require_params(required_params, data, action)
    if r is not None:
      return r
      
    result = { 
      "action":  action,
      "virtualemail": data['virtualemail'] 
    }      
    
    virtualemail_domain = data['virtualemail'].split('@')[1].lower()
    if not virtualemail_domain in self.email_domains:
      result['status']  = "FAIL"
      result['message'] = "Virtualemail is not in the correct domain"
      return (200, result)
      
    if self.validate_key_access(data['virtualemail']) is False:
      result['status']  = "FAIL"
      result['message'] = "Virtualemail is not in an authorized domain"
      return (200, result)
 
    if modify == False and not self.validate_email(data['virtualemail']):
      result['status']  = "FAIL"
      result['message'] = "Virtualemail is not a valid email address"
      return (200, result)
 
    try:
      r = ddb.get_item(self.ddb_tablename, 'virtualemail', data['virtualemail'].lower())
    except Exception as e:
      self.handle_exception(e, "get data from ddb in get()", text=json.dumps(event))
      result['status']  = "FAIL"
      result['message'] = "Internal error (AAOMGD)"
      return (200, result)

    if modify is False and r is not None:
      result['status']  = "FAIL"
      result['message'] = "Virtual account already exists"
      return (200, result)
      
    if modify is True and r is None:
      result['status']  = "FAIL"
      result['message'] = "Virtual account does not exist"
      return (200, result)

    if 'owner' in data:
      # allow bypassing the check by giving an empty list in config
      owner_domain_ok = (len(self.owner_domains) == 0)
      for _domain in self.owner_domains:
        if re.search("@{}$".format(_domain), data['owner'], re.IGNORECASE):
          owner_domain_ok = True
        
      if owner_domain_ok == False:
        result['status']  = "FAIL"
        result['message'] = "Owner email address is not from an authorized domain"
        return (200, result)
        
      _owner = data['owner'].lower()
    else:
      _owner = r['owner']

    rcpts = data['recipients'] if 'recipients' in data else r['recipients']

    try:
      _rcpts = json.loads(rcpts)  
    except json.decoder.JSONDecodeError:
      _rcpts = [x.strip() for x in rcpts.split(',')]

    _recipients = []
    for recipient in _rcpts:
      if not self.validate_email(recipient):
        result['status']  = "FAIL"
        result['message'] = "Recipient {} is not a valid email address".format(recipient)
        return (200, result)
      
      # allow bypassing the check by giving an empty list in config
      _domain_ok = (len(self.recipient_domains) == 0)
      for _domain in self.recipient_domains:
        if re.search("@{}$".format(_domain), recipient, re.IGNORECASE):
          _domain_ok = True
        
      if _domain_ok == False:
        result['status']  = "FAIL"
        result['message'] = "Recipient email address {} is not from an authorized domain; {}".format(recipient, self.recipient_domains)
        return (200, result)

      if recipient not in _recipients:
        _recipients.append(recipient)

    if r is not None and 'protected' in r and r['protected'] != False:
      result['status']  = "FAIL"
      result['message'] = "Virtualemail is protected"
      return (200, result)   
      
    if 'protected' in data and data['protected'] == True:
      _protected = True
    else:
      _protected = False
      
    if 'managed' in data and data['managed'] == False:
      _managed = False
    else:
      _managed = True
    
    d = {
      'virtualemail': data['virtualemail'].lower(),
      'owner':        _owner.lower(),
      'recipients':   json.dumps(_recipients).lower(),
      'protected':    _protected,
      'managed':      _managed
    }
  
    try:
      ddb.put_item(self.ddb_tablename, d)
    except Exception as e:
      self.handle_exception(e, "writing to ddb in _action_add_or_modify()", text=json.dumps(event))
      result['status']  = "FAIL"
      result['message'] = "Internal error (AAOMWD)"
      return (200, result)
        
    result['status']  = "OK"
    return (200, result)  
    
    
  #-------------------------------------------------------------------------#
  

  def get(self, event):
    data   = self._get_data(event)
    action = 'get'
    
    r = self._require_params(['virtualemail'], data, action)
    if r is not None:
      return r

    result = { 
      "action":  action,
      "virtualemail": data['virtualemail'] 
    }
    
    if self.validate_key_access(data['virtualemail']) is False:
      result['status']  = "FAIL"
      result['message'] = "Virtualemail is not in an authorized domain"
      return (200, result)
      
    try:
      r = ddb.get_item(self.ddb_tablename, 'virtualemail', data['virtualemail'].lower())
      result['result'] = r
    except Exception as e:
      self.handle_exception(e, "get data from ddb in get()", text=json.dumps(event))
      result['status']  = "FAIL"
      result['message'] = "Internal error (GGD)"
      return (200, result)
    
    result['status']  = "OK" 
    return (200, result)


  #-------------------------------------------------------------------------#
  
    
  def add(self, event):
    return self._action_add_or_modify(event, 'add')


  #-------------------------------------------------------------------------#
  
  
  def modify(self, event):
    return self._action_add_or_modify(event, 'modify')
  
  
  #-------------------------------------------------------------------------#
  
  
  def delete(self, event):
    data   = self._get_data(event)
    action = 'delete'

    r = self._require_params(['virtualemail', 'owner'], data, action)
    if r is not None:
      return r
      
    result = { 
      "action":  action,
      "virtualemail": data['virtualemail'] 
    }          
    
    if self.validate_key_access(data['virtualemail']) is False:
      result['status']  = "FAIL"
      result['message'] = "Virtualemail is not in an authorized domain"
      return (200, result)    
    
    try:
      r = ddb.get_item(self.ddb_tablename, 'virtualemail', data['virtualemail'])
    except Exception as e:
      self.handle_exception(e, "get data from ddb in delete()", text=json.dumps(event))
      result['status']  = "FAIL"
      result['message'] = "Internal error (DGD)"
      return (200, result)
      
    if r is None:
      result['status']  = "FAIL"
      result['message'] = "Virtual account does not exist"
      return (200, result)
    
    if r['owner'] != data['owner'].lower():
      result['status']  = "FAIL"
      result['message'] = "Owner parameter does not match owner in database"
      return (200, result)
      
    if r['protected'] != False:
      result['status']  = "FAIL"
      result['message'] = "Virtual account is protected"
      return (200, result)    
      
    try:
      ddb.delete_item(self.ddb_tablename, 'virtualemail', data['virtualemail'].lower())
    except Exception as e:
      self.handle_exception(e, "delete data from ddb in delete()", text=json.dumps(event))
      result['status']  = "FAIL"
      result['message'] = "Internal error (DDD)"
      return (200, result)
    
    result['status']  = "OK"    
    return (200, result)

