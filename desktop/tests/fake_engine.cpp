// A protocol peer used only by QProcess integration tests.
//   --diagnostics-once   the first "open" snapshot carries one diagnostic message
//   --refresh-delay=MS   wait before answering "refresh"
//   --refresh-fails      answer "refresh" with an error
//   --open-fails         answer "open" with an error
//   --graph-delay=MS     wait before answering "graph"
#include <QCoreApplication>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QStringList>
#include <QThread>

#include <iostream>
#include <string>

namespace {

struct Options {
    bool diagnosticsOnce = false;
    bool refreshFails = false;
    bool openFails = false;
    int refreshDelay = 0;
    int graphDelay = 0;
};

Options parseOptions(const QStringList &arguments) {
    Options options;
    options.diagnosticsOnce = arguments.contains("--diagnostics-once");
    options.refreshFails = arguments.contains("--refresh-fails");
    options.openFails = arguments.contains("--open-fails");
    for (const auto &argument : arguments) {
        if (argument.startsWith("--refresh-delay="))
            options.refreshDelay = argument.section('=', 1).toInt();
        if (argument.startsWith("--graph-delay="))
            options.graphDelay = argument.section('=', 1).toInt();
    }
    return options;
}

QString errorMessage(const QString &method) {
    if (method == "refresh")
        return "refresh failed";
    if (method == "open")
        return "open failed";
    return "recoverable";
}

QJsonObject snapshot(int generation, bool withDiagnostic) {
    const auto messages = withDiagnostic ? QJsonArray{"problem"} : QJsonArray{};
    return QJsonObject{{"generation", generation},
                       {"entries", QJsonArray{}},
                       {"messages", messages},
                       {"documents", QJsonArray{}}};
}

QJsonObject respond(const QJsonObject &request, const Options &options, int &generation) {
    const auto method = request["method"].toString();
    if (method == "refresh" && options.refreshDelay > 0)
        QThread::msleep(options.refreshDelay);
    if (method == "graph" && options.graphDelay > 0)
        QThread::msleep(options.graphDelay);
    const bool reject = method == "reject"; // as the worker answers an unreadable frame
    const bool fail = method == "fail" || reject || (method == "refresh" && options.refreshFails) ||
                      (method == "open" && options.openFails);
    QJsonObject response{{"protocol_version", method == "bad-version" ? 99 : 1},
                         {"id", reject ? QJsonValue::Null : request["id"]},
                         {"ok", !fail}};
    if (fail) {
        response["error"] = QJsonObject{{"code", "example"}, {"message", errorMessage(method)}};
    } else if (method == "open") {
        ++generation;
        response["result"] = QJsonObject{
            {"snapshot", snapshot(generation, options.diagnosticsOnce && generation == 1)}};
    } else if (method == "refresh") {
        response["result"] = QJsonObject{{"changed", false}};
    } else {
        response["result"] = QJsonObject{};
    }
    return response;
}

} // namespace

int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    const auto options = parseOptions(app.arguments());
    int generation = 0;
    std::string line;
    while (std::getline(std::cin, line)) {
        const auto request = QJsonDocument::fromJson(QByteArray::fromStdString(line)).object();
        const auto bytes =
            QJsonDocument(respond(request, options, generation)).toJson(QJsonDocument::Compact);
        std::cout << bytes.toStdString() << '\n' << std::flush;
    }
    return 0;
}
