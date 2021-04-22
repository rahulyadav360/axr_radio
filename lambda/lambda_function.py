"""
 Copyright (C) 2020 Dabble Lab - All Rights Reserved
 You may use, distribute and modify this code under the
 terms and conditions defined in file 'LICENSE.txt', which
 is part of this source code package.
 
 For additional copyright information please
 visit : http://dabblelab.com/copyright
 """

import logging
import json
import random
import requests
import os
import boto3

from ask_sdk_core.utils import is_request_type, is_intent_name
from ask_sdk_core.api_client import DefaultApiClient
from ask_sdk_core.skill_builder import CustomSkillBuilder
from ask_sdk_model.ui import AskForPermissionsConsentCard
from ask_sdk_model.services import ServiceException
from ask_sdk_dynamodb.adapter import DynamoDbAdapter
from ask_sdk_model.interfaces.display import (Image, ImageInstance)
from ask_sdk_core.dispatch_components import (AbstractRequestHandler, AbstractExceptionHandler, AbstractRequestInterceptor, AbstractResponseInterceptor)
from ask_sdk_model.interfaces.audioplayer import (PlayDirective, PlayBehavior, AudioItem, Stream, AudioItemMetadata,StopDirective, ClearQueueDirective, ClearBehavior)
from utils import (create_presigned_url, get_stream_data)

# Initializing the logger and setting the level to "INFO"
# Read more about it here https://www.loggly.com/ultimate-guide/python-logging-basics/
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Defining the database region, table name and dynamodb persistence adapter
ddb_region = os.environ.get('DYNAMODB_PERSISTENCE_REGION')
ddb_table_name = os.environ.get('DYNAMODB_PERSISTENCE_TABLE_NAME')
ddb_resource = boto3.resource('dynamodb', region_name=ddb_region)
dynamodb_adapter = DynamoDbAdapter(table_name=ddb_table_name, create_table=False, dynamodb_resource=ddb_resource)

# Define location permissions required by the skill
location_permissions = ["read::alexa:device:all:address"]

# Intent Handlers

# This handler checks if the device supports audio playback
class CheckAudioInterfaceHandler(AbstractRequestHandler):

    def can_handle(self, handler_input):
        if handler_input.request_envelope.context.system.device:
            return handler_input.request_envelope.context.system.device.supported_interfaces.audio_player is None
        else:
            return False

    def handle(self, handler_input):
        language_prompts = handler_input.attributes_manager.request_attributes["_"]
        speech_output = language_prompts["DEVICE_NOT_SUPPORTED"]
        
        return (
            handler_input.response_builder
                .speak(speech_output)
                .set_should_end_session(True)
                .response
            )

# This handler starts the stream playback whenever a user invokes the skill or resumes playback.
class LaunchRequestHandler(AbstractRequestHandler):
    def can_handle(self,handler_input):
        return is_request_type("LaunchRequest")(handler_input)

    def handle(self,handler_input):
        language_prompts = handler_input.attributes_manager.request_attributes["_"]
        persistent_attributes = handler_input.attributes_manager.persistent_attributes
        session_attributes = handler_input.attributes_manager.session_attributes
        
        try:
            device_id = handler_input.request_envelope.context.system.device.device_id
            device_addr_client = handler_input.service_client_factory.get_device_address_service()
            full_address = device_addr_client.get_full_address(device_id)
            print(full_address)
        except ServiceException as exception:
            if exception.status_code == 403:
                return (
                    handler_input.response_builder
                        .speak(random.choice(language_prompts["ENABLE_LOCATION_PERMISSIONS"]))
                        .set_card(AskForPermissionsConsentCard(permissions=location_permissions))
                        .response
                    )
            else:
                return (
                    handler_input.response_builder
                        .speak(random.choice(language_prompts["ERROR_FETCHING_LOCATION"]))
                        .set_should_end_session(True)
                        .response
                    )
                    
        if persistent_attributes.get('stream_data') is None:
            speech_output = random.choice(language_prompts["WELCOME_MESSAGE"])
            if full_address.country_code is None:
                stream_data = get_stream_data('default')
                speech_output = speech_output + random.choice(language_prompts["ADDRESS_NOT_AVAILABLE"])
            else:
                stream_data = get_stream_data(full_address.country_code)
                if stream_data is not None:
                    country_name = stream_data['country_name']
                    speech_output = speech_output + random.choice(language_prompts["PLAY_COUNTRY_STREAM"]).format(country_name,country_name)
                else:
                    stream_data = get_stream_data('default')
                    speech_output = speech_output + random.choice(language_prompts["PLAY_DEFAULT_STREAM"])
                
            persistent_attributes['stream_data'] = stream_data
            handler_input.attributes_manager.save_persistent_attributes()
                
        else:
            speech_output = random.choice(language_prompts["WELCOME_BACK_MESSAGE"])
            stream_data = persistent_attributes['stream_data']
            default_stream_data = get_stream_data('default')
                
            if full_address.country_code is not None:
                if stream_data['stream_url'] == default_stream_data['stream_url']:
                    new_stream_data = get_stream_data(full_address.country_code)
                    if new_stream_data is not None:
                        country_name = new_stream_data['country_name']
                        speech_output = speech_output + random.choice(language_prompts["COUNTRY_STREAM_AVAILABLE"]).fomat(country_name,country_name)
                        reprompt = random.choice(language_prompts["COUNTRY_STREAM_AVAILABLE_REPROMPT"])
                        session_attributes['stream_data'] = new_stream_data
                        
                        return (
                            handler_input.response_builder
                                .speak(speech_output)
                                .ask(reprompt)
                                .response
                            )
            
        return (
            handler_input.response_builder
                .speak(speech_output)
                .add_directive(
                            PlayDirective(
                                play_behavior=PlayBehavior.REPLACE_ALL,
                                audio_item=AudioItem(
                                    stream=Stream(
                                        token = 'token',
                                        url = stream_data['stream_url'],
                                        offset_in_milliseconds = 0
                                        ),
                                    metadata = AudioItemMetadata(
                                        title = stream_data['stream_title'],
                                        subtitle = stream_data['stream_subtitle'],
                                        art = Image(
                                            sources = [
                                                ImageInstance(
                                                    url = stream_data['album_art']
                                                )
                                            ]
                                        ),
                                        background_image = Image(
                                            sources = [
                                                ImageInstance(
                                                    url = stream_data['background_image']
                                                )
                                            ]
                                        ),
                                    )
                                )
                            )
                        )
                .set_should_end_session(True)
                .response
            )

class YesIntentHandler(AbstractRequestHandler):
    def can_handle(self,handler_input):
        return is_intent_name("AMAZON.YesIntent")(handler_input)
        
    def handle(self,handler_input):
        language_prompts = handler_input.attributes_manager.request_attributes["_"]
        persistent_attributes = handler_input.attributes_manager.persistent_attributes
        session_attributes = handler_input.attributes_manager.session_attributes
        
        stream_data = session_attributes['stream_data']
        persistent_attributes['stream_data'] = stream_data
        handler_input.attributes_manager.save_persistent_attributes()
        
        return ( 
            handler_input.response_builder
                    .add_directive(
                        PlayDirective(
                            play_behavior=PlayBehavior.REPLACE_ALL,
                            audio_item=AudioItem(
                                stream=Stream(
                                    token = 'token',
                                    url = stream_data['stream_url'],
                                    offset_in_milliseconds = 0
                                    ),
                                metadata = AudioItemMetadata(
                                    title = stream_data['stream_title'],
                                    subtitle = stream_data['stream_subtitle'],
                                    art = Image(
                                        sources = [
                                            ImageInstance(
                                                url = stream_data['album_art']
                                            )
                                        ]
                                    ),
                                    background_image = Image(
                                        sources = [
                                            ImageInstance(
                                                url = stream_data['background_image']
                                            )
                                        ]
                                    ),
                                )
                            )
                        )
                    )
                    .set_should_end_session(True)
                    .response
                )

class NoIntentHandler(AbstractRequestHandler):
    def can_handle(self,handler_input):
        return is_intent_name("AMAZON.NoIntent")(handler_input)
        
    def handle(self,handler_input):
        persistent_attributes = handler_input.attributes_manager.persistent_attributes
        stream_data = persistent_attributes['stream_data']
        
        return ( 
            handler_input.response_builder
                    .add_directive(
                        PlayDirective(
                            play_behavior=PlayBehavior.REPLACE_ALL,
                            audio_item=AudioItem(
                                stream=Stream(
                                    token = 'token',
                                    url = stream_data['stream_url'],
                                    offset_in_milliseconds = 0
                                    ),
                                metadata = AudioItemMetadata(
                                    title = stream_data['stream_title'],
                                    subtitle = stream_data['stream_subtitle'],
                                    art = Image(
                                        sources = [
                                            ImageInstance(
                                                url = stream_data['album_art']
                                            )
                                        ]
                                    ),
                                    background_image = Image(
                                        sources = [
                                            ImageInstance(
                                                url = stream_data['background_image']
                                            )
                                        ]
                                    ),
                                )
                            )
                        )
                    )
                    .set_should_end_session(True)
                    .response
                )

class PauseIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return (
            is_request_type("PlaybackController.PauseCommandIssued")(handler_input)
            or is_intent_name("AMAZON.PauseIntent")(handler_input)
            )
    
    def handle(self, handler_input):
        return ( 
            handler_input.response_builder
                .add_directive(
                    ClearQueueDirective(
                        clear_behavior=ClearBehavior.CLEAR_ALL)
                    )
                .add_directive(StopDirective())
                .set_should_end_session(True)
                .response
            )

class ResumeIntentHandler(AbstractRequestHandler):
    def can_handle(self,handler_input):
        return (
            is_request_type("PlaybackController.PlayCommandIssued")(handler_input)
            or is_intent_name("AMAZON.ResumeIntent")(handler_input)
            )
                
    def handle(self,handler_input):
        language_prompts = handler_input.attributes_manager.request_attributes["_"]
        persistent_attributes = handler_input.attributes_manager.persistent_attributes
        session_attributes = handler_input.attributes_manager.session_attributes
        
        stream_data = persistent_attributes['stream_data']
        
        return ( 
            handler_input.response_builder
                .add_directive(
                    PlayDirective(
                        play_behavior = PlayBehavior.REPLACE_ALL,
                        audio_item = AudioItem(
                            stream = Stream(
                                token = 'token',
                                url = stream_data['stream_url'],
                                offset_in_milliseconds = 0
                                ),
                            metadata = AudioItemMetadata(
                                title = stream_data['stream_title'],
                                subtitle = stream_data['stream_subtitle'],
                                art = Image(
                                    sources = [
                                        ImageInstance(
                                            url = stream_data['album_art']
                                        )
                                    ]
                                ),
                                background_image = Image(
                                    sources = [
                                        ImageInstance(
                                            url = stream_data['background_image']
                                        )
                                    ]
                                ),
                            )
                        )
                    )
                )
                .set_should_end_session(True)
                .response
            )

# This handler handles all the required audio player intents which are not supported by the skill yet. 
class UnhandledFeaturesIntentHandler(AbstractRequestHandler):
    def can_handle(self,handler_input):
        return (is_intent_name("AMAZON.LoopOnIntent")(handler_input)
                or is_intent_name("AMAZON.NextIntent")(handler_input)
                or is_intent_name("AMAZON.PreviousIntent")(handler_input)
                or is_intent_name("AMAZON.RepeatIntent")(handler_input)
                or is_intent_name("AMAZON.ShuffleOnIntent")(handler_input)
                or is_intent_name("AMAZON.StartOverIntent")(handler_input)
                or is_intent_name("AMAZON.ShuffleOffIntent")(handler_input)
                or is_intent_name("AMAZON.LoopOffIntent")(handler_input)
                )
    
    def handle(self, handler_input):
        language_prompts = handler_input.attributes_manager.request_attributes["_"]
        speech_output = random.choice(language_prompts["UNHANDLED"])
        return (
            handler_input.response_builder
                .speak(speech_output)
                .set_should_end_session(True)
                .response
            )

# This handler provides the user with basic info about the skill when a user asks for it.
# Note: This would only work with one shot utterances and not during stream playback.
class AboutIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AboutIntent")(handler_input)
    
    def handle(self, handler_input):
        language_prompts = handler_input.attributes_manager.request_attributes["_"]
        
        speech_output = random.choice(language_prompts["ABOUT"])
        reprompt = random.choice(language_prompts["ABOUT_REPROMPT"])
        return (
            handler_input.response_builder
                .speak(speech_output)
                .ask(reprompt)
                .response
            )

class HelpIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.HelpIntent")(handler_input)
    
    def handle(self, handler_input):
        language_prompts = handler_input.attributes_manager.request_attributes["_"]
        speech_output = random.choice(language_prompts["HELP"])
        reprompt = random.choice(language_prompts["HELP_REPROMPT"])
        
        return (
            handler_input.response_builder
                .speak(speech_output)
                .ask(reprompt)
                .response
            )

class CancelOrStopIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return (
            is_intent_name("AMAZON.CancelIntent")(handler_input)
            or is_intent_name("AMAZON.StopIntent")(handler_input)
            )
    
    def handle(self, handler_input):
        language_prompts = handler_input.attributes_manager.request_attributes["_"]
        return ( 
            handler_input.response_builder
                .speak(random.choice(language_prompts["CANCEL_STOP_MESSAGE"]))
                .set_should_end_session(True)
                .response
            )

class PlaybackStartedEventHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_request_type("AudioPlayer.PlaybackStarted")(handler_input)
    
    def handle(self, handler_input):
        return ( handler_input.response_builder
                    .add_directive(
                        ClearQueueDirective(
                            clear_behavior=ClearBehavior.CLEAR_ENQUEUED)
                        )
                    .response
                )

class PlaybackStoppedEventHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ( is_request_type("PlaybackController.PauseCommandIssued")(handler_input)
                or is_request_type("AudioPlayer.PlaybackStopped")(handler_input)
            )
    
    def handle(self, handler_input):
        return ( handler_input.response_builder
                    .add_directive(
                        ClearQueueDirective(
                            clear_behavior=ClearBehavior.CLEAR_ALL)
                        )
                    .add_directive(StopDirective())
                    .set_should_end_session(True)
                    .response
                )

# This handler tries to play the stream again if the playback failed due to any reason.
class PlaybackFailedEventHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_request_type("AudioPlayer.PlaybackFailed")(handler_input)
    
    def handle(self,handler_input):
        return handler_input.response_builder.response
    

# This handler handles utterances that can't be matched to any other intent handler.
class FallbackIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.FallbackIntent")(handler_input)
    
    def handle(self, handler_input):
        language_prompts = handler_input.attributes_manager.request_attributes["_"]
        speech_output = random.choice(language_prompts["FALLBACK"])
        reprompt = random.choice(language_prompts["FALLBACK_REPROMPT"])
        
        return (
            handler_input.response_builder
                .speak(speech_output)
                .ask(reprompt)
                .response
            )


class SessionEndedRequestHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_request_type("SessionEndedRequest")(handler_input)
    
    def handle(self, handler_input):
        logger.info("Session ended with reason: {}".format(handler_input.request_envelope.request.reason))
        return handler_input.response_builder.response


class ExceptionEncounteredRequestHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_request_type("System.ExceptionEncountered")(handler_input)
    
    def handle(self, handler_input):
        logger.info("Session ended with reason: {}".format(handler_input.request_envelope.request.reason))
        return handler_input.response_builder.response

# Interceptors

# This interceptor is used for supporting different languages and locales. It detects the users locale,
# loads the corresponding language prompts and sends them as a request attribute object to the handler functions.
class LocalizationInterceptor(AbstractRequestInterceptor):

    def process(self, handler_input):
        locale = handler_input.request_envelope.request.locale
        
        try:
            with open("languages/"+str(locale)+".json") as language_data:
                language_prompts = json.load(language_data)
        except:
            with open("languages/"+ str(locale[:2]) +".json") as language_data:
                language_prompts = json.load(language_data)
        
        handler_input.attributes_manager.request_attributes["_"] = language_prompts

# This interceptor logs each request sent from Alexa to our endpoint.
class RequestLogger(AbstractRequestInterceptor):

    def process(self, handler_input):
        logger.debug("Alexa Request: {}".format(
            handler_input.request_envelope.request))

# This interceptor logs each response our endpoint sends back to Alexa.
class ResponseLogger(AbstractResponseInterceptor):

    def process(self, handler_input, response):
        logger.debug("Alexa Response: {}".format(response))

# This exception handler handles syntax or routing errors. If you receive an error stating 
# the request handler is not found, you have not implemented a handler for the intent or 
# included it in the skill builder below
class CatchAllExceptionHandler(AbstractExceptionHandler):
    
    def can_handle(self, handler_input, exception):
        return True
    
    def handle(self, handler_input, exception):
        logger.error(exception, exc_info=True)
        
        language_prompts = handler_input.attributes_manager.request_attributes["_"]
        
        speech_output = language_prompts["ERROR"]
        reprompt = language_prompts["ERROR_REPROMPT"]
        
        return (
            handler_input.response_builder
                .speak(speech_output)
                .ask(reprompt)
                .response
            )

# Skill Builder
# Define a skill builder instance and add all the request handlers,
# exception handlers and interceptors to it.

sb = CustomSkillBuilder(api_client=DefaultApiClient(), persistence_adapter = dynamodb_adapter)
sb.add_request_handler(CheckAudioInterfaceHandler())
sb.add_request_handler(LaunchRequestHandler())
sb.add_request_handler(PauseIntentHandler())
sb.add_request_handler(ResumeIntentHandler())
sb.add_request_handler(UnhandledFeaturesIntentHandler())
sb.add_request_handler(CancelOrStopIntentHandler())
sb.add_request_handler(HelpIntentHandler())
sb.add_request_handler(AboutIntentHandler())
sb.add_request_handler(FallbackIntentHandler())
sb.add_request_handler(PlaybackStartedEventHandler())
sb.add_request_handler(PlaybackStoppedEventHandler())
sb.add_request_handler(PlaybackFailedEventHandler())
sb.add_request_handler(SessionEndedRequestHandler())

sb.add_exception_handler(CatchAllExceptionHandler())

sb.add_global_request_interceptor(LocalizationInterceptor())
sb.add_global_request_interceptor(RequestLogger())
sb.add_global_response_interceptor(ResponseLogger())

lambda_handler = sb.lambda_handler()
