from channels.generic.websocket import JsonWebsocketConsumer
from asgiref.sync import async_to_sync
from django.apps import apps
from django.template.loader import render_to_string
from django.core.signing import Signer, BadSignature

from turbo import make_channel_name


class TurboStreamsConsumer(JsonWebsocketConsumer):
    def connect(self):
        self.requests = dict()
        self.accept()

    def notify(self, event, *args, **kwargs):
        model_label = event["model"]
        model = apps.get_model(model_label)

        pk = event["pk"]
        action = event["action"]

        if action == "append" or action == "prepend":
            dom_target = model._meta.verbose_name_plural.lower()
        else:
            dom_target = f'{model._meta.verbose_name.lower()}_{pk}'

        for request_id in self.requests[event["channel_name"]]:
            instance = model.objects.get(pk=pk)
            app, model_name = model_label.lower().split(".")

            self.send_json({
                "request_id": request_id,
                "data": render_to_string('turbo/stream.html', {
                    "object": instance,
                    model_name.lower(): instance,
                    "action": action,
                    "dom_target": dom_target,
                    "model_template": f"{app}/{model_name}.html"
                })
            })

    def receive_json(self, content, **kwargs):
        signer = Signer()
        request_id = content.get("request_id")
        message_type = content.get("type")
        if message_type == "subscribe":
            try:
                channel_name = signer.unsign(content.get("signed_channel_name", ""))
            except BadSignature:
                print("Signature has been tampered with!")
                return

            self.requests.setdefault(channel_name, []).append(request_id)
            self.groups.append(channel_name)
            async_to_sync(self.channel_layer.group_add)(channel_name, self.channel_name)
        elif message_type == "unsubscribe":
            try:
                channel_name = [channel_name for channel_name, requests in self.requests.items() if request_id in requests][0]
            except IndexError:
                return  # No subscription for a given request ID exists.
            self.groups.remove(channel_name)
            if channel_name not in self.groups:
                async_to_sync(self.channel_layer.group_discard)(channel_name, self.channel_name)

