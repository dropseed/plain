# Signals

**Run code when certain events happen in your application.**

- [Overview](#overview)
- [Using the receiver decorator](#using-the-receiver-decorator)
- [Creating custom signals](#creating-custom-signals)
- [Filtering by sender](#filtering-by-sender)
- [Signal methods](#signal-methods)
    - [send](#send)
    - [send_robust](#send_robust)
    - [disconnect](#disconnect)
    - [has_listeners](#has_listeners)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

Signals let you decouple parts of your application by allowing certain senders to notify receivers when specific events occur. You connect a receiver function to a signal, and it gets called whenever that signal is sent.

```python
from plain.signals import request_finished


def on_request_finished(sender, **kwargs):
    print("Request finished!")


request_finished.connect(on_request_finished)
```

Plain provides two built-in signals:

- `request_started` - sent when a request begins processing
- `request_finished` - sent when a request finishes processing

Your receiver function must accept `**kwargs` because signals may pass additional arguments in the future.

## Using the receiver decorator

Instead of calling `.connect()` manually, you can use the `@receiver` decorator to connect a function to a signal.

```python
from plain.signals import request_finished
from plain.signals.dispatch import receiver


@receiver(request_finished)
def on_request_finished(sender, **kwargs):
    print("Request finished!")
```

You can also connect to multiple signals at once by passing a list.

```python
from plain.signals import request_started, request_finished
from plain.signals.dispatch import receiver


@receiver([request_started, request_finished])
def on_request_event(sender, **kwargs):
    print("Request event occurred!")
```

## Creating custom signals

You can define your own signals for custom events in your application.

```python
from plain.signals.dispatch import Signal

# Define a custom signal
order_placed = Signal()


# Connect a receiver
@receiver(order_placed)
def send_order_confirmation(sender, order, **kwargs):
    print(f"Order {order.id} placed, sending confirmation email...")


# Send the signal from your code
def create_order(data):
    order = Order.objects.create(**data)
    order_placed.send(sender=Order, order=order)
    return order
```

## Filtering by sender

You can connect a receiver to only respond to signals from a specific sender.

```python
from plain.signals.dispatch import Signal, receiver

payment_received = Signal()


@receiver(payment_received, sender="stripe")
def handle_stripe_payment(sender, **kwargs):
    # Only called when sender="stripe"
    print("Stripe payment received!")


# This will trigger the receiver
payment_received.send(sender="stripe", amount=100)

# This will NOT trigger the receiver
payment_received.send(sender="paypal", amount=100)
```

## Signal methods

### send

Sends the signal to all connected receivers. If a receiver raises an exception, it propagates immediately and stops further receivers from being called.

```python
responses = my_signal.send(sender=MyClass, data="example")
for receiver, response in responses:
    print(f"{receiver} returned {response}")
```

### send_robust

Like `send()`, but catches exceptions from receivers and returns them as part of the response list instead of propagating them. This ensures all receivers get called.

```python
responses = my_signal.send_robust(sender=MyClass, data="example")
for receiver, response in responses:
    if isinstance(response, Exception):
        print(f"{receiver} raised {response}")
    else:
        print(f"{receiver} returned {response}")
```

### disconnect

Removes a receiver from the signal. You typically don't need to call this since receivers use weak references by default and are automatically removed when garbage collected.

```python
my_signal.disconnect(my_receiver)
```

### has_listeners

Checks if any receivers are connected to the signal.

```python
if my_signal.has_listeners():
    my_signal.send(sender=MyClass)
```

## FAQs

#### Why must receivers accept `**kwargs`?

This allows signals to add new arguments in the future without breaking existing receivers. When `DEBUG` is enabled, Plain validates that your receivers accept `**kwargs` and raises an error if they don't.

#### What is `dispatch_uid` for?

When connecting a receiver, you can provide a `dispatch_uid` to prevent the same receiver from being connected multiple times. This is useful when your connection code might run more than once.

```python
request_finished.connect(my_receiver, dispatch_uid="my_unique_id")
```

#### Can I use strong references instead of weak references?

By default, signals use weak references to receivers, so receivers are automatically disconnected when they go out of scope. If you need to keep a receiver connected even after its normal lifecycle, pass `weak=False` to `.connect()`.

```python
my_signal.connect(my_receiver, weak=False)
```

#### How do I see all receivers connected to a signal?

You can inspect the `receivers` attribute on the signal, though this is primarily for debugging. For checking if any receivers exist, use [`has_listeners()`](./dispatch/dispatcher.py#has_listeners).

## Installation

Signals are included as part of Plain and do not require separate installation.

```python
from plain.signals import request_started, request_finished
from plain.signals.dispatch import Signal, receiver
```
