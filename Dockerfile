# channeliq - IPTV stream verification and visual curation
#
# Docker is the supported install path on purpose: it makes ffmpeg, ffprobe and
# a known Python version identical on Windows, macOS and Linux, and it is the
# install method the *arr-stack audience already uses. The image carries no
# Python dependencies at all -- channeliq is standard library only.
FROM alpine:3.20

RUN apk add --no-cache python3 ffmpeg tzdata ca-certificates

WORKDIR /app
COPY channeliq/ /app/channeliq/
# Compatibility shim: probarr was renamed to channeliq, but README's own
# documented cron/scripting invocation was `python3 -m probarr ...` --
# anyone with that in an existing script or cron job would hit a hard
# ModuleNotFoundError the moment they pulled the renamed image, with no
# warning and no way to know why. A plain copy under the old name keeps
# `python3 -m probarr` working identically, indefinitely, at the cost of
# one duplicated (tiny, pure-Python) directory in the image.
RUN cp -r /app/channeliq /app/probarr

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CHANNELIQ_CONFIG=/config \
    CHANNELIQ_PORT=7799

VOLUME ["/config"]
EXPOSE 7799

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- http://127.0.0.1:7799/ >/dev/null 2>&1 || exit 1

ENTRYPOINT ["python3", "-m", "channeliq"]
CMD ["serve"]
