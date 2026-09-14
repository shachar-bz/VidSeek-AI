"""Object storage services, one package per backend.

Cloudflare R2 holds the video files themselves. Everything that describes a video —
jobs, transcripts, metadata — is destined for Supabase and is not configured yet, so R2
is the only backend here today.
"""
