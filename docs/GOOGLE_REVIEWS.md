# Live Google reviews

The homepage displays genuine reviews from the selected verified Google Business Profile. It loads up to 50 reviews per Google API page; Show more makes subsequent pages available without restricting the feed to the Places API's review selection. Reviews are ordered by update time and are not filtered by rating. No review text is stored on disk.

## One-time setup

1. In your Google Cloud project, obtain Google Business Profile API access and enable the Google My Business API, Business Profile Account Management API, and Business Profile Business Information API. Business Profile API access may require Google's approval.
2. Configure the OAuth consent screen with scope `https://www.googleapis.com/auth/business.manage`. During testing, add the owner account as a test user. Testing-mode refresh tokens can expire after seven days; use the appropriate production publishing/verification process before deployment.
3. Create an OAuth **Web application** client. Add this exact local authorized redirect URI: `http://localhost:8000/api/v1/website/reviews/google/callback`.
4. In backend/.env set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and GOOGLE_REDIRECT_URI (see .env.example). Restart the backend. Do not put the secret in frontend environment variables or commit it.
5. Sign in as administrator, open the website editor, and choose Google reviews → Connect Google → Continue to Google authorization. Grant access using the account managing the listing.
6. Close the confirmation tab, choose Refresh connection, select the correct business, and Publish reviews from this business.

On deployment set GOOGLE_REDIRECT_URI to the backend's HTTPS callback URL and add that exact URI to the OAuth client. Multiple managed listings are supported. The supplied Maps short link is the public review link; it cannot authorize API access or determine which managed listing to publish.

The refresh token and pending PKCE state are stored in the ignored website_data/google-business-private.json file with owner-only permissions. This file is never exposed through a public API. Back it up privately alongside the website data. Disconnect Google deletes the local token; access can also be revoked in Google account settings.

When disconnected or unavailable, visitors can still open the Google listing. No sample reviews or invented ratings are displayed. Public results use a short in-memory cache to reduce API requests; restarting clears the cache.

References: https://developers.google.com/my-business/content/implement-oauth and https://developers.google.com/my-business/reference/rest/v4/accounts.locations.reviews/list
