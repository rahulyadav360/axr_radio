import requests
import logging
import os
import boto3
import json
import random

from botocore.exceptions import ClientError



def create_presigned_url(object_name):
    s3_client = boto3.client('s3',
                             region_name=os.environ.get('S3_PERSISTENCE_REGION'),
                             config=boto3.session.Config(signature_version='s3v4',s3={'addressing_style': 'path'}))
    try:
        bucket_name = os.environ.get('S3_PERSISTENCE_BUCKET')
        response = s3_client.generate_presigned_url('get_object',
                                                    Params={'Bucket': bucket_name,
                                                            'Key': object_name},
                                                    ExpiresIn=6000)
    except ClientError as e:
        logging.error(e)
        return None

    # The response contains the presigned URL
    return response

def get_stream_data(country_code):
    stream_db_json = open ('stream_db.json', "r")
    stream_db = json.loads(stream_db_json.read())
    stream_data = stream_db.get(country_code)
    return stream_data