#include "chartbrowser.h"

#include <QFileInfo>
#include <QLineEdit>
#include <QSignalBlocker>
#include <QSortFilterProxyModel>
#include <QStandardItemModel>
#include <QStyle>
#include <QTreeView>
#include <QVBoxLayout>

namespace flowcharts {
namespace {
enum Role { DocumentRole = Qt::UserRole + 1, QualnameRole, SearchRole, MessageRole, LineRole };

QStandardItem *chartItem(const QString &label, int document, const QString &qualname,
                         const QString &search) {
    auto *item = new QStandardItem(label);
    item->setEditable(false);
    item->setData(document, DocumentRole);
    item->setData(qualname, QualnameRole);
    item->setData(search + ' ' + label, SearchRole);
    return item;
}
} // namespace

ChartBrowser::ChartBrowser(QWidget *parent)
    : QWidget(parent), m_search(new QLineEdit(this)), m_tree(new QTreeView(this)),
      m_model(new QStandardItemModel(this)), m_filter(new QSortFilterProxyModel(this)) {
    auto *layout = new QVBoxLayout(this);
    layout->setContentsMargins(6, 6, 6, 6);
    m_search->setPlaceholderText("Search functions or files…");
    m_search->setClearButtonEnabled(true);
    m_search->setAccessibleName("Search charts");
    layout->addWidget(m_search);
    layout->addWidget(m_tree);
    m_filter->setSourceModel(m_model);
    m_filter->setFilterRole(SearchRole);
    m_filter->setFilterCaseSensitivity(Qt::CaseInsensitive);
    m_filter->setRecursiveFilteringEnabled(true);
    m_filter->setAutoAcceptChildRows(true);
    m_tree->setModel(m_filter);
    m_tree->setHeaderHidden(true);
    m_tree->setUniformRowHeights(true);
    m_tree->setAccessibleName("Files and charts");
    connect(m_search, &QLineEdit::textChanged, this, [this](const QString &text) {
        m_filter->setFilterFixedString(text);
        m_tree->expandAll();
    });
    connect(m_tree->selectionModel(), &QItemSelectionModel::currentChanged, this,
            [this](const QModelIndex &index) {
                if (!index.isValid())
                    return;
                if (index.data(QualnameRole).isValid())
                    emit chartSelected(index.data(DocumentRole).toInt(),
                                       index.data(QualnameRole).toString());
                else
                    emit fileSelected(index.data(DocumentRole).toInt(),
                                      index.data(MessageRole).toString(),
                                      index.data(LineRole).toInt());
            });
}

void ChartBrowser::setWorkspace(const Workspace &workspace) {
    const QSignalBlocker blocker(m_tree->selectionModel());
    m_model->clear();
    auto *calls = chartItem("Call graph", -1, "", "call graph");
    calls->setIcon(style()->standardIcon(QStyle::SP_ComputerIcon));
    m_model->appendRow(calls);
    for (const auto &value : workspace.entries()) {
        const auto entry = value.toObject();
        const int document = entry["doc"].isDouble() ? entry["doc"].toInt() : -1;
        const auto path = entry["source"].toString();
        const auto key = entry["key"].toString();
        auto *file = new QStandardItem(key + '.' + QFileInfo(path).suffix());
        file->setEditable(false);
        file->setIcon(style()->standardIcon(entry["error"].isString() ? QStyle::SP_MessageBoxWarning
                                                                      : QStyle::SP_FileIcon));
        file->setToolTip(path);
        file->setData(document, DocumentRole);
        file->setData(key + ' ' + path, SearchRole);
        file->setData(entry["error"].toString(), MessageRole);
        m_model->appendRow(file);
        if (entry["has_module"].toBool())
            file->appendRow(chartItem("<module>", document, "<module>", key));
        for (const auto &function : entry["functions"].toArray()) {
            const auto name = function.toObject()["qualname"].toString();
            file->appendRow(chartItem(name, document, name, key));
        }
        for (const auto &value : entry["skipped"].toArray()) {
            const auto skipped = value.toObject();
            auto *item = new QStandardItem(skipped["qualname"].toString() + " (skipped)");
            item->setEditable(false);
            item->setIcon(style()->standardIcon(QStyle::SP_MessageBoxWarning));
            item->setData(document, DocumentRole);
            item->setData(key + ' ' + skipped["qualname"].toString(), SearchRole);
            item->setData(skipped["message"].toString(), MessageRole);
            item->setData(skipped["line"].toInt(), LineRole);
            file->appendRow(item);
        }
    }
    m_tree->expandAll();
}

void ChartBrowser::selectChart(const ChartRef &ref) {
    const QSignalBlocker blocker(m_tree->selectionModel());
    const auto visit = [this, &ref](QStandardItem *item) {
        if (item->data(QualnameRole).isValid() &&
            item->data(DocumentRole).toInt() == ref.document &&
            item->data(QualnameRole).toString() == ref.qualname) {
            const auto index = m_filter->mapFromSource(item->index());
            m_tree->setCurrentIndex(index);
            return true;
        }
        return false;
    };
    for (int row = 0; row < m_model->rowCount(); ++row) {
        auto *item = m_model->item(row);
        if (visit(item))
            return;
        for (int child = 0; child < item->rowCount(); ++child) {
            if (visit(item->child(child)))
                return;
        }
    }
    m_tree->clearSelection();
}

void ChartBrowser::focusSearch() {
    m_search->setFocus();
    m_search->selectAll();
}

} // namespace flowcharts
