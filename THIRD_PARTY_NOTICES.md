# Third-party notices

## proxy-scraper-checker source catalog

`config/sources.json` contains HTTPS feed URLs derived from the source lists in [`monosans/proxy-scraper-checker`](https://github.com/monosans/proxy-scraper-checker), tag `build-3872`. ProxyScout does not include or modify that project's Rust source code. The checker executable is installed separately from the same tagged release.

The upstream project is MIT-licensed:

```text
MIT License

Copyright (c) 2021 monosans

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Additional feed URL metadata

The feed catalog also includes directly parseable HTTPS source URLs derived from the provider configuration in [`bluet/proxybroker2`](https://github.com/bluet/proxybroker2) and the active fetcher list in [`jhao104/proxy_pool`](https://github.com/jhao104/proxy_pool). ProxyBroker2 is licensed under Apache-2.0; ProxyPool is licensed under MIT. ProxyScout does not include or modify either project's Python implementation. See the upstream [ProxyBroker2 license](https://github.com/bluet/proxybroker2/blob/master/LICENSE) and [ProxyPool license](https://github.com/jhao104/proxy_pool/blob/master/LICENSE).
