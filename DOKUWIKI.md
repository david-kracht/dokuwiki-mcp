

```bash
# username: root
# password: root
# groups  : admin, user
# token   : eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJkb2t1d2lraSIsInN1YiI6InJvb3QiLCJpYXQiOjE3NzU5NDM0MTF9.0h5hzv1ms4VcTqabkJFeK9/YuvOKbqz+5ReuohwCWFA=

# username: mcp-read
# password: mcp
# groups  : api, read
# token   : eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJkb2t1d2lraSIsInN1YiI6Im1jcC1yZWFkIiwiaWF0IjoxNzc1OTQzMTk5fQ==.rBdJZeCuNIUQrVjHv7p14aogj0aSWDwWjftweYIiRZY=

# username: mcp-write
# password :mcp
# groups  : api, write
# token   : eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJkb2t1d2lraSIsInN1YiI6Im1jcC13cml0ZSIsImlhdCI6MTc3NTk0MzU1NH0=.hhQNhX96m2ZTEAg31mMZYNmiv/UDUQEva1WpE1puZbw=

```

```bash
# BASIC AUTH
user_pass="mcp-read:mcp"
curl http://localhost:8080/lib/exe/jsonrpc.php/core.getPageInfo \
   -u $user_pass \
   -H 'Content-Type: application/json' \
   -d '{"page": "start"}'

user_pass="mcp-read:mcp"
curl http://localhost:8080/lib/exe/jsonrpc.php/core.getPageInfo \
   -H 'Content-Type: application/json' \
   -H "Authorization: Basic $(echo -n $user_pass | base64)" \
   -d '{"page": "start"}'


token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJkb2t1d2lraSIsInN1YiI6Im1jcC1yZWFkIiwiaWF0IjoxNzc1OTQzMTk5fQ==.rBdJZeCuNIUQrVjHv7p14aogj0aSWDwWjftweYIiRZY=
curl http://localhost:8080/lib/exe/jsonrpc.php/core.getPageInfo \
   -H 'Content-Type: application/json' \
   -H "Authorization: Bearer $token" \
   -d '{"page": "start"}'

# TOKEN JSON RPC (Please note, when using version 2.0, batching multiple calls is not supported. [see](https://www.dokuwiki.org/devel:jsonrpc) )
token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJkb2t1d2lraSIsInN1YiI6Im1jcC1yZWFkIiwiaWF0IjoxNzc1OTQzMTk5fQ==.rBdJZeCuNIUQrVjHv7p14aogj0aSWDwWjftweYIiRZY=
curl http://localhost:8080/lib/exe/jsonrpc.php \
   -H 'Content-Type: application/json' \
   -H "Authorization: Bearer $token" \
   -d '{"jsonrpc": "2.0", "id": "something", "method": "core.getPage", "params": {"page": "start"}}'

token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJkb2t1d2lraSIsInN1YiI6Im1jcC1yZWFkIiwiaWF0IjoxNzc1OTQzMTk5fQ==.rBdJZeCuNIUQrVjHv7p14aogj0aSWDwWjftweYIiRZY=
curl http://localhost:8080/lib/exe/jsonrpc.php/core.getPageInfo \
   -H 'Content-Type: application/json' \
   -H "x-dokuwiki-token: $token" \
   -d '{"page": "start"}'
```