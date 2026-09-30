// Links made before the landing page moved (invitations, bookmarks) still point at /#/...; send them to the app.
if (location.hash.startsWith('#/')) location.replace('/app' + location.hash);
addEventListener('hashchange', () => { if (location.hash.startsWith('#/')) location.replace('/app' + location.hash); });
