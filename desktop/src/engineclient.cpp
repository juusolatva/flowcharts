#include "engineclient.h"

#include <algorithm>

namespace flowcharts {

EngineClient::EngineClient(QObject *parent) : QObject(parent) {
    m_deadline.setSingleShot(true);
    connect(&m_process, &QProcess::started, this, &EngineClient::dispatch);
    connect(&m_process, &QProcess::readyReadStandardOutput, this, &EngineClient::readOutput);
    connect(&m_process, &QProcess::readyReadStandardError, this, [this] {
        m_stderr += m_process.readAllStandardError();
        m_stderr = m_stderr.right(8192);
    });
    connect(&m_process, &QProcess::errorOccurred, this, [this](QProcess::ProcessError error) {
        if (error == QProcess::FailedToStart)
            fail("Could not start the analysis engine: " + m_process.errorString() +
                 "\nCheck the engine executable and its dependencies.");
        else if (error == QProcess::Crashed)
            fail("The analysis engine crashed.\n" + QString::fromUtf8(m_stderr));
    });
    connect(&m_process, &QProcess::finished, this, [this](int code, QProcess::ExitStatus) {
        if (!m_stopping)
            fail(QString("The analysis engine exited (code %1).\n%2")
                     .arg(code)
                     .arg(QString::fromUtf8(m_stderr)));
    });
    connect(&m_deadline, &QTimer::timeout, this,
            [this] { fail("The analysis engine stopped responding. Restart it from File."); });
}

EngineClient::~EngineClient() {
    stop();
}

void EngineClient::stop() {
    m_stopping = true;
    m_deadline.stop();
    m_queue.clear();
    m_active.reset();
    if (m_process.state() != QProcess::NotRunning) {
        m_process.closeWriteChannel();
        if (!m_process.waitForFinished(300)) {
            m_process.kill();
            m_process.waitForFinished(1000);
        }
    }
}

void EngineClient::start(const QString &program, const QStringList &arguments,
                         const QString &workingDirectory) {
    stop();
    m_stopping = false;
    m_failed = false;
    m_stderr.clear();
    m_reader.clear();
    if (program.isEmpty()) {
        QTimer::singleShot(0, this, [this] {
            fail("Could not find the analysis engine. Install uv and put it on PATH, or choose "
                 "an engine with --engine.");
        });
        return;
    }
    m_process.setProcessChannelMode(QProcess::SeparateChannels);
    m_process.setWorkingDirectory(workingDirectory);
    m_process.start(program, arguments);
    m_deadline.start(120000);
}

qint64 EngineClient::request(const QString &method, const QJsonObject &params) {
    const qint64 id = m_nextId++;
    if (m_failed) {
        QTimer::singleShot(0, this, [this, id, method] {
            emit failed(id, method, "disconnected", "Restart the analysis engine from File.");
        });
        return id;
    }
    if (method == "open") {
        m_queue.clear();
    } else if (method == "graph") {
        m_queue.erase(std::remove_if(m_queue.begin(), m_queue.end(),
                                     [](const Request &r) { return r.method == "graph"; }),
                      m_queue.end());
    }
    m_queue.append({id, method, params});
    emit busyChanged(true);
    dispatch();
    return id;
}

bool EngineClient::idle() const {
    return running() && !m_active && m_queue.isEmpty();
}

bool EngineClient::running() const {
    return !m_failed && m_process.state() == QProcess::Running;
}

void EngineClient::dispatch() {
    if (!running() || m_active)
        return;
    m_deadline.stop();
    if (m_queue.isEmpty()) {
        emit busyChanged(false);
        return;
    }
    m_active = m_queue.takeFirst();
    if (m_process.write(encodeRequest(m_active->id, m_active->method, m_active->params)) < 0) {
        fail("Could not send a request to the analysis engine");
        return;
    }
    // Analysing a workspace takes as long as the workspace needs. A layout is bounded by the
    // engine's own 30-second Graphviz limit, so a silent layout request means a hung engine.
    if (m_active->method == "graph")
        m_deadline.start(m_layoutTimeout);
}

void EngineClient::readOutput() {
    QVector<QJsonObject> frames;
    if (QString error; !m_reader.feed(m_process.readAllStandardOutput(), frames, error)) {
        fail(error);
        return;
    }
    for (const auto &frame : frames) {
        accept(frame);
        if (m_failed)
            break;
    }
}

void EngineClient::accept(const QJsonObject &response) {
    if (response["protocol_version"] != QJsonValue(ProtocolVersion)) {
        fail("Incompatible engine protocol; this GUI requires protocol version 1");
        return;
    }
    // The worker answers a frame it could not read with a null ID. Only one request is ever in
    // flight, so that answer belongs to it; it is an ordinary failure, not a broken session.
    if (const bool unreadable = response["id"].isNull() && response["ok"] == QJsonValue(false);
        !m_active || (!unreadable && response["id"] != QJsonValue(m_active->id)) ||
        !response["ok"].isBool()) {
        fail("Unexpected response from the analysis engine");
        return;
    }
    const bool ok = response["ok"].toBool();
    if ((ok && !response["result"].isObject()) ||
        (!ok &&
         (!response["error"].isObject() || !response["error"].toObject()["code"].isString() ||
          !response["error"].toObject()["message"].isString()))) {
        fail("Malformed response from the analysis engine");
        return;
    }
    const auto completed = *m_active;
    m_active.reset();
    m_deadline.stop();
    if (ok) {
        emit succeeded(completed.id, completed.method, response["result"].toObject());
    } else {
        const auto error = response["error"].toObject();
        emit failed(completed.id, completed.method, error["code"].toString(),
                    error["message"].toString());
    }
    dispatch();
}

void EngineClient::fail(const QString &message) {
    if (m_failed || m_stopping)
        return;
    m_failed = true;
    m_deadline.stop();
    m_queue.clear();
    m_active.reset();
    m_process.kill();
    emit busyChanged(false);
    emit fatalError(message);
}

} // namespace flowcharts
