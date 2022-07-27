#!/usr/bin/env python3

from yascheduler import Yascheduler

yac = Yascheduler()
label = "test dummy calc"
result = yac.queue_submit_task(
    label,
    {
        "1.input": "ABC" * 100,
        "2.input": "DEF" * 100,
        "3.input": "Q" * 1000,
        "webhook_url": "https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXXXXXX",
    },
    "dummy",
)

print(label)
print(result)
