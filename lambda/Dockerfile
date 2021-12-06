FROM public.ecr.aws/lambda/python:3.9
COPY functions .
COPY requirements.txt .
RUN python3 -m pip install -r requirements.txt -t .
CMD [ "virtualmail.default.lambda_handler" ]
