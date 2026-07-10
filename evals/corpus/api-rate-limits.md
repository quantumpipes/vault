# API Rate Limits

Each API key is allowed 600 requests per minute, with a short burst allowance of 100. Exceeding the ceiling returns HTTP 429 with a Retry-After header indicating when to try again.
