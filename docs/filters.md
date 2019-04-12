# Modifying Filters

You may be familiar with the use of special elements in Logban filter regular expressions such as stripping an IP address or port number from a line.  For example you can strip an ip and port number using `{rhost}` and `{port}` which will later be available to your triggers:

    /var/log/auth.log  | auth_failed | ^Authentication Failed for host {rhost} on port {port} 

This is achieved with two Logban features:

### Named regular expressions (AKA named_groups).

Technically any python named group will be converted into a named parameter and passed with your event.  So for example if you wanted to strip out an email you might filter for lines in "example.log" such as:

    Authentication failed for email bad.person@example.com

You could do this without a plugin by just specifying a named group `(?P<email>...)` with a regular expression.  However the result would be difficult to understand.  A much better way is to specify a named_group to the filter mechanism:

    from logban.filter import named_groups

    logban.filter.named_groups['email'] = r'(?P<email>[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,})'

This allows a much neater config:

    # These two lines now do exactly the same thing...
    /var/log/example.log  | auth_failed | ^Authentication failed for email {email}$
    /var/log/example.log  | auth_failed | ^Authentication failed for email (?P<email>[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,})$


### Param Processors

Following on from the email example. Its sometimes useful to post-process parameters before they are published in events.  This can be done with Param Processors.  Param processors are free to add modify and remove all parameters.

    from logban.filter import param_processors

    def _split_email(params):
        if 'email' in params:
            parts = params.split('@')
            params['email_user'] = parts[0]
            params['email_domain'] = parts[1]

    param_processors.append(split_email)
