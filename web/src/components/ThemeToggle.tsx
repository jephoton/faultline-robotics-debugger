import { useTheme } from '../lib/theme';
import { Icon } from './Icon';

export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const next = theme === 'dark' ? 'light' : 'dark';
  return (
    <button type="button" className="btn btn--secondary btn--small theme-toggle" onClick={toggle}>
      <Icon name={next === 'dark' ? 'moon' : 'sun'} />
      Use {next} theme
    </button>
  );
}
