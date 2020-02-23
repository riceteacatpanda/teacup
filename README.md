# Teacup
Forked from https://gitlab.com/Milkdrop/microbot

A Discord bot that takes care of challenge dockers for X-MAS CTF.

![MicroBot](https://htsp.ro/assets/images/posts/X-MAS_CTF_Logistics/microbot.png)

You can run it through another python3 script such as:

```python
import os
while True:
    os.system ("python3 microbot.py")
```

So that you can be sure the bot will remain up (since discord.py likes exiting after a while).

The `dockers` file included in this repository is the `dockers` file from X-MAS CTF 2019, and is an example of how you can format such a file yourself:
```python
{
    "Category1": {
        "Problem1": [
            {
                EXTERNAL_PORT:INTERNAL_PORT,
                "EXT_PORT_RANGE-EXT_PORT_RANGE":"INT_PORT_RANGE-INT_PORT_RANGE"
            },
            MAX_RAM_USAGE_MB (optional, default = 100),
            MAX_CPU_USAGE (optional, default = 0.1)
        ]
    },
    "Category2": {
        "Problem1": [
            {
                EXTERNAL_PORT:INTERNAL_PORT,
            }
        ]
    }
}
```
