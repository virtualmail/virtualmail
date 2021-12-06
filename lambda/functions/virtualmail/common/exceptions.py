class PassthroughException(Exception):
    
  def __init__(self, e, when, text=None, stop_processing=False):
    self.msg  = 'Exception "{}" while {}'.format(e, when)
    self.e    = e
    self.when = when
    self.text = text
    self.stop_processing = stop_processing
    super().__init__(self.msg)