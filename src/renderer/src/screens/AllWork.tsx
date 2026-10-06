// 全部项目 / All work: the live lane + every batch / project / work folder, without importing anything.
import { HistoryList } from '../components/HistoryList';
import { t } from '../i18n';
import { href } from '../lib/router';

export function AllWork() {
  return (
    <>
      <div className="topbar">
        <h1>{t('nav.allWork')}</h1>
        <div className="sp" />
        <a className="btn primary" href={href({ name: 'new' })}>
          {t('batches.new')}
        </a>
      </div>
      <div className="page">
        <HistoryList full />
      </div>
    </>
  );
}
