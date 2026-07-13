# REST API — Sending Related (Deliveries)

_Last updated: over 3 years ago_

## Call Address

| Data Center | URL |
|---|---|
| Singapore | https://email.api.engagelab.cc |
| Turkey | https://emailapi-tr.engagelab.com |

When using the REST API, ensure that the selected data center corresponds to the appropriate base URL.

---

## POST /v1/mail/send — Regular Delivery

**URL**

```
https://email.api.engagelab.cc/v1/mail/send
```

**Content-Type**

```
application/json;charset=utf-8
```

**HTTP Request Method**: `POST`

### Request Header

| Header | Type | Required | Description |
|---|---|---|---|
| Authorization | String | true | Basic base64(api_user:api_key) |

### Request Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| from | string | yes | From. Example: `support@mail.engagelab.com`, `EngageLab Team<support@mail.engagelab.com>`. If a product or company brand name needs to be displayed, use `EngageLab Team<support@mail.engagelab.com>` — `EngageLab Team` is the from name and can transmit the product or company brand name, `<support@mail.engagelab.com>` is the sender address. |
| to | array[string] | yes | Recipients. Up to 100 addresses are supported. Example: `["xjm@hotmail.com","xjm2@gmail.com"]` |
| body | object | yes | Mail settings |
| custom_args | object | no | Optional fields customized by the customer. Maximum size 1KB. The key value of custom_args cannot contain the `.` symbol. |
| request_id | string | no | ID of this sending request; 128 characters maximum. |

### Body

| Parameter | Type | Required | Description |
|---|---|---|---|
| cc | array[string] | no | Cc. Maximum of 100 addresses. Only valid when `send_mode=1`. |
| bcc | array[string] | no | Bcc. Maximum of 100 addresses. Only valid when `send_mode=1`. |
| reply_to | array[string] | no | Reply to. Up to 3 addresses. If no value is transferred, the reply-to address is `from`. |
| subject | string | yes | Subject. 256 characters max; supports variables, emoji. |
| content | object | yes | Content |
| vars | object | no | Variables. Up to 1MB. Valid when `send_mode=0` or `send_mode=1`. |
| dynamic_vars | array[object] | no | Dynamic template variables. Max size 1MB. Valid when `send_mode=0` or `send_mode=1`. |
| label_id | string | no | Label ID used for this sending |
| label_name | string | no | Label name used for this sending |
| headers | object | no | Headers. Up to 1KB. |
| attachments | array[object] | no | Attachments. Total size must not exceed 10MB. |
| settings | object | no | Send settings |

### Tips

- When `send_mode=2`, the value of `to` is an address list nickname, and the number cannot exceed 5. In this case, the `cc` and `bcc` parameters are invalid.
- `html` and `plain` cannot both be empty.
- `preview_text` can only be used with `html`. If no `html` value is transferred, `preview_text` will not take effect.
- `vars` is used for variable replacement in mail content. Format: JSON object `{"varname": ["value1","value2"]}`, where `varname` is the mail content variable. If the variable value passed is empty or a space, the corresponding text in the email will be displayed as empty.

  Message content: `Dear %name%, welcome to %sp% email service.`

  Corresponding vars value: `{"name": ["mike"], "sp": ["engagelab"]}`

  Email content after replacement: `Dear Mike, welcome to engagelab email service.`

- `dynamic_vars` is used for replacing variables in dynamic templates. Format: JSON object, e.g. `[{"varname1":"value1","varname2":"value2"}]`.

  Email content: `Dear {{name}}, welcome to use {{sp}} email service.`

  Value passed in `dynamic_vars`: `[{"name":"jim","sp":"engagelab"}]`

  Replaced email content: `Dear jim, welcome to use engagelab email service.`

- Users can pass either `label_id` or `label_name` for this transmission. If `label_name` does not exist, the system will automatically create it. If both `label_id` and `label_name` are passed, `label_name` will be ignored.
- `headers` is used to customize the header fields of the message. Format: JSON object, e.g. `{"User-Define": "123", "User-Custom": "abc"}`. The key string cannot contain the following values (case insensitive): `DKIM-Signature`, `Received`, `Sender`, `Date`, `From`, `To`, `Reply-To`, `Cc`, `Bcc`, `Subject`, `Content-Type`, `Content-Transfer-Encoding`, `X-SENDCLOUD-UUID`, `X-SENDCLOUD-LOG`, `X-Remote-Web-IP`, `X-SMTPAPI`, `Return-Path`, `X-SENDCLOUD-LOG-NEW`.
- When `disposition` is set to `inline`, the attachment content is an image, and the attachment will be rendered and displayed directly in the message body as an inline image. `content_id` must be set and be a unique string, used as the `src` when the picture is displayed in the message body.

  Email content:

  ```html
  <html>
      <img src="cid:image_1000"></img>
      <img src="cid:image_1001"></img>
  </html>
  ```

  `attachments` parameter:

  ```json
  [
    {"content": "base64 image content", "filename": "a23456.jpg", "disposition": "inline", "content_id": "image_1000"},
    {"content": "base64 image content", "filename": "a23457.jpg", "disposition": "inline", "content_id": "image_1001"}
  ]
  ```

- `custom_args`, as defined by the customer, will be embedded in the header; the subsequent WebHook data will return it to you. The key value of `custom_args` cannot contain the `.` symbol.
- `request_id` is used to prevent repeated submission, and is valid for 1 hour. If submitted repeatedly within 1 hour, the last request result will be returned.
- The total email size cannot exceed 70MB.

### Request Example

```bash
curl -X POST -H 'Content-Type: application/json; charset=utf-8' \
     -H 'Authorization: Basic YXBpX3VzZXI6YXBpX2tleQ==' \
     --data '{
  "from": "EngageLab Newsletter <newsletter@mail.engagelab.com>",
  "to": ["111@qq.com", "222<222@qq.com>"],
  "body": {
      "cc": ["noreply@mail.engagelab.com"],
      "bcc": ["intern<intern@mail.engagelab.com>"],
      "reply_to": ["reply@mail.engagelab.com"],
      "subject": "%date% Newsletter",
      "content": {
        "html": "<a href=\"https://www.engagelab.com\">Newsletter %kkk%</a>",
        "text": "Today'"'"'s news is %ttt%",
        "preview_text": "preview_text is ..."
      },
      "vars": {},
      "label_id": 100233,
      "label_name": "",
      "headers": {},
      "attachments": [{
        "content": "The Base64 encoded content of the attachment",
        "type": "text/html",
        "filename": "The attachment'"'"'s filename",
        "disposition": "inline | attachment",
        "content_id": ""
      }],
      "settings": {
        "send_mode": 0,
        "return_email_id": true,
        "sandbox": true,
        "notification": false,
        "open_tracking": true,
        "click_tracking": false,
        "unsubscribe_tracking": true,
        "unsubscribe_page_id": [1, 2]
      }
  },
  "custom_args": {},
  "request_id": ""
}' 'https://email.api.engagelab.cc/v1/mail/send'
```

### Response Examples

**Non address-list sending (`send_mode=0` or `send_mode=1`)**

Response — success (`HTTP 200`)

```json
{
  "email_ids": [
    "1447054895514_15555555_32350_1350.sc-10_10_126_221-inbound0$111@qq.com",
    "1447054895514_15555555_32350_1350.sc-10_10_126_221-inbound1$222@qq.com"
  ],
  "request_id": ""
}
```

Response — error (`HTTP 400`)

```json
{
  "code": 30801,
  "message": "From can not be empty"
}
```

**Address-list sending (`send_mode=2`)**

Response — success (`HTTP 200`)

```json
{
  "task_id": [102923],
  "request_id": ""
}
```

Response — error (`HTTP 400`)

```json
{
  "code": 30801,
  "message": "From can not be empty"
}
```

---

## POST /v1/mail/sendtemplate — Template Delivery

**URL**

```
https://email.api.engagelab.cc/v1/mail/sendtemplate
```

**Content-Type**

```
application/json; charset=utf-8
```

**HTTP Request Method**: `POST`

### Request Header

| Header | Type | Required | Description |
|---|---|---|---|
| Authorization | String | true | Basic base64(api_user:api_key) |

### Request Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| from | string | yes | From. Example: `support@mail.engagelab.com`, `EngageLab Team<support@mail.engagelab.com>`. If a product or company brand name needs to be displayed, use `EngageLab Team<support@mail.engagelab.com>` — `EngageLab Team` is the from name and can transmit the product or company brand name, `<support@mail.engagelab.com>` is the sender address. |
| to | array[string] | yes | Recipients. Up to 100 addresses are supported. Example: `["xjm@hotmail.com","xjm2@gmail.com"]` |
| body | object | yes | Mail settings |
| custom_args | object | no | Optional fields customized by the customer. Maximum size 1KB. The key value of custom_args cannot contain the `.` symbol. |
| request_id | string | no | ID of this sending request; 128 characters maximum. |

### Body

| Parameter | Type | Required | Description |
|---|---|---|---|
| cc | array[string] | no | Cc. Maximum of 100 addresses. Only valid when `send_mode=1`. |
| bcc | array[string] | no | Bcc. Maximum of 100 addresses. Only valid when `send_mode=1`. |
| reply_to | array[string] | no | Reply to. Up to 3 addresses. If no value is transferred, the reply-to address is `from`. |
| subject | string | no | Subject. 256 characters max; supports variables, emoji. |
| template_invoke_name | string | yes | Template invoke name. |
| vars | object | no | Variables. Up to 1MB. Valid when `send_mode=0` or `send_mode=1`. |
| dynamic_vars | array[object] | no | Dynamic template variables. Max size 1MB. Valid when `send_mode=0` or `send_mode=1`. |
| label_id | string | no | Label ID used for this sending |
| label_name | string | no | Label name used for this sending |
| headers | object | no | Headers. Up to 1KB. |
| attachments | array[object] | no | Attachments. Total size must not exceed 10MB. |
| settings | object | no | Send settings |

### Tips

- When `send_mode=2`, the value of `to` is an address list nickname, and the number cannot exceed 5. In this case, the `cc` and `bcc` parameters are invalid.
- `vars` is used for variable replacement in mail content. Format: JSON object `{"varname": ["value1","value2"]}`, where `varname` is the mail content variable. If the variable value passed is empty or a space, the corresponding text in the email will be displayed as empty.

  Message content: `Dear %name%, welcome to %sp% email service.`

  Corresponding vars value: `{"name": ["mike"], "sp": ["engagelab"]}`

  Email content after replacement: `Dear Mike, welcome to engagelab email service.`

- `dynamic_vars` is used for replacing variables in dynamic templates. Format: JSON object, e.g. `[{"varname1":"value1","varname2":"value2"}]`.

  Email content: `Dear {{name}}, welcome to use {{sp}} email service.`

  Value passed in `dynamic_vars`: `[{"name":"jim","sp":"engagelab"}]`

  Replaced email content: `Dear jim, welcome to use engagelab email service.`

- Users can pass either `label_id` or `label_name` for this transmission. If `label_name` does not exist, the system will automatically create it. If both `label_id` and `label_name` are passed, `label_name` will be ignored.
- `headers` is used to customize the header fields of the message. Format: JSON object, e.g. `{"User-Define": "123", "User-Custom": "abc"}`. The key string cannot contain the following values (case insensitive): `DKIM-Signature`, `Received`, `Sender`, `Date`, `From`, `To`, `Reply-To`, `Cc`, `Bcc`, `Subject`, `Content-Type`, `Content-Transfer-Encoding`, `X-SENDCLOUD-UUID`, `X-SENDCLOUD-LOG`, `X-Remote-Web-IP`, `X-SMTPAPI`, `Return-Path`, `X-SENDCLOUD-LOG-NEW`.
- When `disposition` is set to `inline`, the attachment content is an image, and the attachment will be rendered and displayed directly in the message body as an inline image. `content_id` must be set and be a unique string, used as the `src` when the picture is displayed in the message body.

  Email content:

  ```html
  <html>
      <img src="cid:image_1000"></img>
      <img src="cid:image_1001"></img>
  </html>
  ```

  `attachments` parameter:

  ```json
  [
    {"content": "base64 image content", "filename": "a23456.jpg", "disposition": "inline", "content_id": "image_1000"},
    {"content": "base64 image content", "filename": "a23457.jpg", "disposition": "inline", "content_id": "image_1001"}
  ]
  ```

- `custom_args`, as defined by the customer, will be embedded in the header; the subsequent WebHook data will return it to you. The key value of `custom_args` cannot contain the `.` symbol.
- `request_id` is used to prevent repeated submission, and is valid for 1 hour. If submitted repeatedly within 1 hour, the last request result will be returned.
- The total email size cannot exceed 70MB.

### Template Content Example (`month_bill`)

```
Dear %name%:
  Hello! Your consumption amount this month is: %money%.
```

### Regular Delivery (call template `month_bill`)

```bash
curl -X POST "https://email.api.engagelab.cc/v1/mail/sendtemplate" \
--header "Authorization: Basic <<YOUR_API_KEY_HERE>>" \
--header "Content-Type: application/json" \
--data '{
    "from": "support@mail.engagelab.com",
    "to": ["xjmfc@126.com", "xjmfcme@gmail.com"],
    "body": {
        "subject": "test email",
        "template_invoke_name": "month_bill",
        "label_id": 10143,
        "label_name": "",
        "vars": {
            "%name%": ["jack", "jone"],
            "%money%": ["30", "50"]
        },
        "headers": {
            "userdefine-tag-location": "us",
            "userdefine-tag-user": "fashion"
        },
        "attachments": [{
            "content": "The Base64 encoded content of the attachment",
            "filename": "The attachment'"'"'s filename",
            "disposition": "inline | attachment",
            "content_id": ""
        }],
        "settings": {
            "send_mode": 0,
            "return_email_id": true,
            "sandbox": true,
            "notification": false,
            "open_tracking": true,
            "click_tracking": false,
            "unsubscribe_tracking": true,
            "unsubscribe_page_id": [1, 2]
        }
    },
    "custom_args": {},
    "request_id": ""
}'
```

Resulting emails:

```
# xjmfc@126.com received:
Dear jack:
    Hello! Your consumption amount this month is: 30.

# ---------------------------------------------------

# xjmfcme@gmail.com received:
Dear Joe:
    Hello! Your consumption amount this month is: 50.
```

Response — success (`HTTP 200`)

```json
{
  "email_ids": [
    "1447054895514_15555555_32350_1350.sc-10_10_126_221-inbound0$xjmfc@126.com",
    "1447054895514_15555555_32350_1350.sc-10_10_126_221-inbound1$xjmfcme@gmail.com"
  ],
  "request_id": ""
}
```

Response — error (`HTTP 404`)

```
not found
```

### Regular Delivery (call template `month_bill`, address list `users@maillist.email.engagelab.com`)

```bash
curl -X POST "https://email.api.engagelab.cc/v1/mail/sendtemplate" \
--header "Authorization: Basic <<YOUR_API_KEY_HERE>>" \
--header "Content-Type: application/json" \
--data '{
        "from": {"admin@engaelab.com"},
        "to": ["users@maillist.email.engagelab.com"],
        "body": {
            "subject": "bill",
            "template_invoke_name": "month_bill",
            "label": "gangz"
        }
}'
```

Response — success (`HTTP 200`)

```json
{
  "task_id": [102923],
  "request_id": ""
}
```

Response — error (`HTTP 404`)

```
not found
```

---

## POST /v1/mail/sendcalendar — Send Meeting Calendar

**URL**

```
https://email.api.engagelab.cc/v1/mail/sendcalendar
```

**Content-Type**

```
application/json; charset=utf-8
```

**HTTP Request Method**: `POST`

### Request Header

| Header | Type | Required | Description |
|---|---|---|---|
| Authorization | String | true | Basic base64(apiUser:apiKey) |

### Request Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| from | string | yes | From. Example: `support@mail.engagelab.com`, `EngageLab Team<support@mail.engagelab.com>`. If a product or company brand name needs to be displayed, use `EngageLab Team<support@mail.engagelab.com>` — `EngageLab Team` is the from name and can transmit the product or company brand name, `<support@mail.engagelab.com>` is the sender address. |
| to | array[string] | yes | Recipients. Up to 100 addresses are supported. Example: `["xjm@hotmail.com","xjm2@gmail.com"]` |
| body | object | yes | Mail settings |
| custom_args | object | no | Optional fields customized by the customer. Maximum size 1KB. The key value of custom_args cannot contain the `.` symbol. |
| request_id | string | no | ID of this sending request; 128 characters maximum. |

### Body

| Parameter | Type | Required | Description |
|---|---|---|---|
| cc | array[string] | no | Cc. Maximum of 100 addresses. Only valid when `send_mode=1`. |
| bcc | array[string] | no | Bcc. Maximum of 100 addresses. Only valid when `send_mode=1`. |
| reply_to | array[string] | no | Reply to. Up to 3 addresses. If no value is transferred, the reply-to address is `from`. |
| subject | string | yes | Subject. 256 characters max; supports variables, emoji. |
| content | object | yes | Content |
| vars | object | no | Variables. Up to 1MB. Valid when `send_mode=0` or `send_mode=1`. |
| dynamic_vars | array[object] | no | Dynamic template variables. Max size 1MB. Valid when `send_mode=0` or `send_mode=1`. |
| label_id | string | no | Label ID used for this sending |
| label_name | string | no | Label name used for this sending |
| headers | object | no | Headers. Up to 1KB. |
| attachments | array[object] | no | Attachments. Total size must not exceed 10MB. |
| settings | object | no | Send settings |
| calendar | object | yes | Calendar settings |

### Tips

- `html` and `plain` cannot both be empty.
- `preview_text` can only be used with `html`. If no `html` value is transferred, `preview_text` will not take effect.
- `vars` is used for variable replacement in mail content. Format: JSON object `{"varname": ["value1","value2"]}`, where `varname` is the mail content variable. If the variable value passed is empty or a space, the corresponding text in the email will be displayed as empty.

  Message content: `Dear %name%, welcome to %sp% email service.`

  Corresponding vars value: `{"name": ["mike"], "sp": ["engagelab"]}`

  Email content after replacement: `Dear Mike, welcome to engagelab email service.`

- `dynamic_vars` is used for replacing variables in dynamic templates. Format: JSON object, e.g. `[{"varname1":"value1","varname2":"value2"}]`.

  Email content: `Dear {{name}}, welcome to use {{sp}} email service.`

  Value passed in `dynamic_vars`: `[{"name":"jim","sp":"engagelab"}]`

  Replaced email content: `Dear jim, welcome to use engagelab email service.`

- Users can pass either `label_id` or `label_name` for this transmission. If `label_name` does not exist, the system will automatically create it. If both `label_id` and `label_name` are passed, `label_name` will be ignored.
- `headers` is used to customize the header fields of the message. Format: JSON object, e.g. `{"User-Define": "123", "User-Custom": "abc"}`. The key string cannot contain the following values (case insensitive): `DKIM-Signature`, `Received`, `Sender`, `Date`, `From`, `To`, `Reply-To`, `Cc`, `Bcc`, `Subject`, `Content-Type`, `Content-Transfer-Encoding`, `X-SENDCLOUD-UUID`, `X-SENDCLOUD-LOG`, `X-Remote-Web-IP`, `X-SMTPAPI`, `Return-Path`, `X-SENDCLOUD-LOG-NEW`.
- When `disposition` is set to `inline`, the attachment content is an image, and the attachment will be rendered and displayed directly in the message body as an inline image. `content_id` must be set and be a unique string, used as the `src` when the picture is displayed in the message body.

  Email content:

  ```html
  <html>
      <img src="cid:image_1000"></img>
      <img src="cid:image_1001"></img>
  </html>
  ```

  `attachments` parameter:

  ```json
  [
    {"content": "base64 image content", "filename": "a23456.jpg", "disposition": "inline", "content_id": "image_1000"},
    {"content": "base64 image content", "filename": "a23457.jpg", "disposition": "inline", "content_id": "image_1001"}
  ]
  ```

- `custom_args`, as defined by the customer, will be embedded in the header; the subsequent WebHook data will return it to you. The key value of `custom_args` cannot contain the `.` symbol.
- `request_id` is used to prevent repeated submission, and is valid for 1 hour. If submitted repeatedly within 1 hour, the last request result will be returned.
- The total email size cannot exceed 70MB.

### Request Example

```bash
curl -X POST 'https://email.api.engagelab.cc/v1/mail/sendcalendar' \
--header 'Authorization: Basic MTIyNF94am06MTJkOGIwODVlNjZhZGUyMmNlNGIwOWI5NjQ2YWQ1ODE=' \
--header 'Content-Type: application/json' \
--data '{
  "from": "EngageLab Newsletter <newsletter@mail.engagelab.com>",
  "to": ["111@qq.com", "222<222@qq.com>"],
  "body": {
      "cc": ["noreply@mail.engagelab.com"],
      "bcc": ["intern<intern@mail.engagelab.com>"],
      "reply_to": ["reply@mail.engagelab.com"],
      "subject": "%date% Newsletter",
      "content": {
        "html": "<a href=\"https://www.engagelabe.com\">Newsletter %kkk%</a>",
        "text": "Newsletter %ttt%",
        "preview_text": "preview_text is ..."
      },
      "label_id": "1233",
      "label_name": "",
      "headers": {
        "userdefine-tag-location": "us",
        "userdefine-tag-user": "fashion"
      },
      "settings": {
        "send_mode": 0,
        "return_email_id": true,
        "sandbox": true,
        "notification": false,
        "open_tracking": true,
        "click_tracking": false,
        "unsubscribe_tracking": true,
        "unsubscribe_page_id": [1, 2]
      },
      "calendar": {
        "time_zone_id": "America/New_York",
        "start_time": "2020-12-10 10:00:00",
        "end_time": "2020-12-10 12:00:00",
        "title": "meeting titel",
        "organizer": {
          "name": "David",
          "email": "david@mail.engagelab.com"
        },
        "location": "room208",
        "description": "hello",
        "alarm_min_before": 5,
        "participators": [
          {
            "name": "p1",
            "email": "p1@engagelab.org"
          },
          { "email": "p2@engagelab.org", "name": "p2" },
          { "email": "p3@engagelab.org" }
        ],
        "action": {
          "name": "create",
          "uid": "329r239h239888"
        }
      }
  },
  "custom_args": {},
  "request_id": ""
}'
```

### Response Examples

Response — success (`HTTP 200`)

```json
{
  "uid": "20230103T065922Z-uidGen@PC201503200437",
  "email_ids": [
    "1672729159224_15_2942_8497.sc-10_2_226_96-test0$111@qq.com",
    "1672729159224_15_2942_8497.sc-10_2_226_96-test1$222@qq.com"
  ],
  "request_id": ""
}
```

Response — error (`HTTP 400`)

```json
{
  "code": 30801,
  "message": "From can not be empty"
}
```

---

## POST /v1/mail/send_mime — MIME Delivery

**URL**

```
https://email.api.engagelab.cc/v1/mail/send_mime
```

**Content-Type**

```
application/json;charset=utf-8
```

**HTTP Request Method**: `POST`

### Request Header

| Header | Type | Required | Description |
|---|---|---|---|
| Authorization | String | true | Basic base64(api_user:api_key) |

### Request Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| from | string | no | From. Example: `support@mail.engagelab.com`, `EngageLab Team<support@mail.engagelab.com>`. If a product or company brand name needs to be displayed, use `EngageLab Team<support@mail.engagelab.com>` — `EngageLab Team` is the from name and can transmit the product or company brand name, `<support@mail.engagelab.com>` is the sender address. |
| to | array[string] | no | Recipients. Up to 100 addresses are supported. Example: `["xjm@hotmail.com","xjm2@gmail.com"]` |
| body | object | yes | Mail settings |
| custom_args | object | no | Optional fields customized by the customer. Maximum size 1KB. The key value of custom_args cannot contain the `.` symbol. |
| request_id | string | no | ID of this sending request; 128 characters maximum. |

### Body

| Parameter | Type | Required | Description |
|---|---|---|---|
| cc | array[string] | no | Cc addresses. Maximum of 100 addresses. Only valid when `send_mode=1`. |
| bcc | array[string] | no | Bcc addresses. Maximum of 100 addresses. Only valid when `send_mode=1`. |
| reply_to | array[string] | no | Reply-to addresses. Up to 3 addresses. If no value is transferred, the reply-to address is `from`. |
| subject | string | no | Email subject. 256 characters max; supports variables, emoji. |
| content | object | yes | Email body. |
| vars | object | no | Variables. Up to 1MB. Valid when `send_mode=0` or `send_mode=1`. |
| label_id | string | no | Label ID used for this sending |
| label_name | string | no | Label name used for this sending |
| headers | object | no | Email header information. Up to 1KB. |
| settings | object | no | Sending settings. |

### Notes

- `vars` are used for variable replacement in email content, formatted as a JSON object: `{"varname": ["value1","value2"]}`, where `varname` is the variable in the email content.
- Only one of `label_id` or `label_name` takes effect. If both are provided, `label_id` overrides `label_name`. If `label_name` does not exist, the system automatically creates it.

  Email content: `Dear %name%, welcome to %sp% email service.`

  Corresponding vars value: `{"name": ["mike"], "sp": ["engagelab"]}`

  Email content after replacement: `Dear mike, welcome to engagelab email service.`

- `headers` are used to customize the email header fields, formatted as a JSON object: `{"User-Define": "123", "User-Custom": "abc"}`. The key strings cannot contain the following values (case insensitive): `DKIM-Signature`, `Received`, `Sender`, `Date`, `From`, `To`, `Reply-To`, `Cc`, `Bcc`, `Subject`, `Content-Type`, `Content-Transfer-Encoding`, `X-SENDCLOUD-UUID`, `X-SENDCLOUD-LOG`, `X-Remote-Web-IP`, `X-SMTPAPI`, `Return-Path`, `X-SENDCLOUD-LOG-NEW`.
- `custom_args` are custom content defined by the customer, embedded in the email header; it will be returned to the customer in subsequent WebHook data.
- `request_id` is used to prevent duplicate submissions, valid for 1 hour. If submitted repeatedly within 1 hour, the result of the previous request will be returned.
- The total email size cannot exceed 70MB.

### Request Example

```bash
curl -X POST -H 'Content-Type: application/json; charset=utf-8' \
     -H 'Authorization: YXBpX3VzZXI6YXBpX2tleQ==' \
     --data '{
  "from": "EngageLab Newsletter <newsletter@mail.engagelab.com>",
  "to": ["111@qq.com", "222<222@qq.com>"],
  "body": {
      "reply_to": ["reply@mail.engagelab.com"],
      "subject": "%date% Newsletter",
      "content": {
        "raw_message": "Date: Fri, 8 Aug 2025 18:33:00 +0800 (CST)\r\nFrom: TEST <test@trip.com>\r\nReply-To: test_reply@trip.com\r\nTo: fan_tang@trip.com\r\nMessage-ID:......."
      },
      "vars": {},
      "label_id": 100233,
      "headers": {},
      "settings": {
        "send_mode": 0,
        "return_email_id": true,
        "sandbox": false,
        "notification": false,
        "open_tracking": true,
        "click_tracking": false,
        "unsubscribe_tracking": true,
        "unsubscribe_page_id": [1, 2]
      }
  },
  "custom_args": {},
  "request_id": ""
}' 'https://email.api.engagelab.cc/v1/mail/send_mime'
```

> Note: `label_id` may alternatively be passed as `label_name` (e.g. `label_name="test"`) — only one of the two takes effect.

### Response Example

Response — success (`HTTP 200`)

```json
{
  "email_ids": [
    "1447054895514_15555555_32350_1350.sc-10_10_126_221-inbound0$111@qq.com",
    "1447054895514_15555555_32350_1350.sc-10_10_126_221-inbound1$222@qq.com"
  ],
  "request_id": null
}
```

Response — error (`HTTP 400`)

```json
{
  "code": 30893,
  "message": "The custom_args must be json format"
}
```
