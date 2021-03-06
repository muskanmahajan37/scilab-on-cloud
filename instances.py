# importing the global modules
import pexpect
import os
import re
import time
import sys
import psutil


from datetime import datetime
from django.template.loader import render_to_string, get_template
from django.core.mail import EmailMultiAlternatives
# importing the local variables
from soc.settings import PROJECT_DIR
from soc.config import (BIN, SCILAB_FLAGS, SCIMAX_LOADER, UPLOADS_PATH,
                        SCILAB_3, SCILAB_4, SCILAB_5, SCILAB_6, FROM_EMAIL, TO_EMAIL,
                        CC_EMAIL, BCC_EMAIL, SITE)
from website.models import (TextbookCompanionCategoryList, ScilabCloudComment,
                            TextbookCompanionSubCategoryList,
                            TextbookCompanionProposal,
                            TextbookCompanionRevision,
                            TextbookCompanionPreference,
                            TextbookCompanionChapter, TextbookCompanionExample,
                            TextbookCompanionRevision,
                            TextbookCompanionExampleFiles,
                            TextbookCompanionExampleDependency,
                            TextbookCompanionDependencyFiles)
from website.views import get_example_detail
''' An object of class ScilabInstance handles spawning and maintaining of
 multiple scilab instances.

maxsize is the upper bound of number of Scilab instances that can be alive at
 the same time.

instances list maintains a pool of free Scilab instances.

count is the number of Scilab instances alive currently.

spawn_instance method is used to create Pexpect objects, which in turn spawn
 Scilab instance. A new instance is spawned only if the count is not exceeding
 the value of maxsize.

kill_instances method is used to kill the free Scilab instances in the list
 instances, based on the parameter count passed while invoking the method.

get_available_instance method is used to fetch a non-busy Scilab instance.
It receives one from the list instances or else invokes spawn_instances method
 to fetch a new instance to execute the Scilab code. If there are no Scilab
 instances available, the request has to wait until an instance is available.

execute_code method executes the code passed as one of its parameter. It invokes
get_available_instance method, fetches a Scilab instance and executes the code.
After the execution of the code, the Pexpect object containing Scilab instance
 is put back into the instances list.
'''


class ScilabInstance(object):

    # defining instance variables
    def __init__(self):
        self.maxsize = 5
        self.instances = []
        self.count = 0

    # spawning an instance
    def spawn_instance(self):
        if (self.count < self.maxsize):
            SCILAB_BIN = BIN + '/'
            SCILAB_BIN += SCILAB_6
            SCILAB_BIN += '/bin/scilab-adv-cli'
            new_instance = pexpect.spawn(SCILAB_BIN)
            self.count += 1
            print ("scilab-adv-cli" in (p.name() for p in psutil.process_iter()), "scilab-adv-cli is running")
            try:
                new_instance.expect('-->', timeout=30)
                self.instances.append(new_instance)
            except:
                new_instance.close()
                self.count -= 1

    # killing some spawned instances
    def kill_instances(self, count):
        for i in range(count):
            instance = self.instances.pop(0)
            instance.close()
            self.count -= 1

    # returns an active_instancescilab instance. This will block till it gets an
    # active_instance.
    def get_available_instance(self):
        if not self.instances and self.count < self.maxsize:
            self.spawn_instance()
        while not self.instances:
            pass
        return self.instances.pop(0)

    def execute_code(
            self, code, token, book_id, dependency_exists, chapter_id,
            example_id):
        # Check for system commands
        # print code, token, book_id, dependency_exists
        system_commands = re.compile(
            'unix\(.*\)|unix_g\(.*\)|unix_w\(.*\)|'
            'unix_x\(.*\)|unix_s\(.*\)|host|newfun'
            '|execstr|ascii|mputl|dir\(\)'
        )
        if system_commands.search(code):
            return {
                'output': 'System Commands not allowed',
            }
        # check for clear
        clc_exist = re.compile(r'clear.*all|clear|clc\(\)|clc\\|\bclc\b')
        if clc_exist.search(code):
            add_clear = True
        else:
            add_clear = False

        # Remove all clear;
        code = re.sub(r'clear.*all|clear|clc\(\)|clc\\|\bclc\b', '', code)

        plot_exists = False

        # Finding the plot and appending xs2jpg function
        #p = re.compile(r'.*plot.*\(.*\).*\n|bode\(.*\)|evans\(.*\)')
        p = re.compile(
            r'plot\(.*\)|plot2d.*\(.*\)|plot3d.*\(.*\)|bode\(.*\)|\bstem\(.*\)(\n|;)\b|evans\(.*\)|sgrid\(.*\)|plzr\(.*\)|hallchart\(.*\)|gainplot\(.*\)|nyquist\(.*\)|black\(.*\)|phaseplot\(.*\)|zgrid\(.*\)|show_margins\(.*\)|m_circle\(.*\)')

        plot_path = ''
        ################################
        #if p.search(code):
        plot_exists = True
        code = code + '\n'
        current_time = time.time()
        plot_path = PROJECT_DIR + \
                '/static/tmp/{0}.png'.format(str(current_time))
            #code += 'xs2jpg(gcf(), "{0}");\n'.format(plot_path)
        ################################
        # Check whether to load scimax / maxima
        if 'syms' in code or 'Syms' in code:
            code = code.replace('syms', 'Syms')
            code = 'exec(\'{0}\');\nmaxinit\n'.format(SCIMAX_LOADER) + code

        file_path = PROJECT_DIR + '/static/tmp/' + token + '.sci'

        # traps even syntax errors eg: endfunton
        f = open(file_path, "w")
        if add_clear:
            f.write('clear;\n')
        f.write('driver("PNG");\n')
        f.write('xinit("{0}");\n'.format(plot_path))
        f.write('mode(2);\n')
        if dependency_exists == True and book_id != 0 and chapter_id != 0 \
                and example_id != 0:
            f.write(
                'cd("{0}/{1}/DEPENDENCIES/");\n'.format(UPLOADS_PATH, book_id)
            )
        f.write('lines(0);\n')
        f.write(code)
        f.write('\nxend();')
        f.close()

        cmd = 'exec("' + file_path + '", 2);'
        if(self.count < 1):
            self.spawn_instance()
        active_instance = self.get_available_instance()
        active_instance.sendline(cmd)

        try:
            active_instance.expect('\[0m ', timeout=30)
            active_instance.expect('', timeout=30)
            output = self.trim(active_instance.before.decode('utf-8'))
            self.instances.append(active_instance)

        except:
            active_instance.before += 'Exception Occured: It seems that you \
            are running an infinite code'.encode('ascii')
            output = self.trim(active_instance.before.decode('utf-8'))

            if(self.count > 1):
                active_instance.close()
                self.count -= 1
            if(self.count == 0):
                self.spawn_instance()
        p_file_path = plot_path.replace(PROJECT_DIR, '')
        plot_file_path = PROJECT_DIR + p_file_path
        plot_path = os.path.isfile(plot_file_path)
        plot_return = ""
        if (plot_path == True):
            plot_return = p_file_path
        else:
            plot_retrun = 0
        data = {
            'output': output,
            'plot_path': plot_return
        }

        if '!--error' in output:
            now = datetime.now()
            log_file_name = now.strftime("%Y-%m-%d")
            if book_id != 0 and chapter_id != 0 and example_id != 0:
                book = TextbookCompanionPreference.objects.using('scilab')\
                    .filter(id=book_id)
                chapter = TextbookCompanionChapter.objects.using('scilab')\
                    .filter(id=chapter_id)
                example = TextbookCompanionExample.objects.using('scilab')\
                    .filter(id=example_id)
                f = open(PROJECT_DIR + '/static/log/' +
                         str(log_file_name) + '.txt', "a")
                f.write("***************START****************" + "\n")
                f.write(str(datetime.now()) + "\n")
                f.write("------------------------------------" + "\n")
                f.write("(ID: {2})Book: {0} [Author: {1}]\n".format(
                    book[0].book, book[0].author, book_id))
                f.write("Chapter: {0}\n".format(chapter[0].name))
                f.write("Example: ({0}) {1}\n".format(
                    example[0].number, example[0].caption))
                f.write("------------------------------------" + "\n")
                f.write("Output" + "\n")
                f.write("------------------------------------" + "\n")
                f.write(output + "\n")
                f.write("****************END*****************" + "\n")
            context = {}
            if int(example_id) !=0:
                context = get_example_detail(example_id)
            context['example_id'] = int(example_id)
            context['code'] = code
            context['site_name'] = SITE
            context['output'] = output
            subject = "[Scilab On Cloud] Error in scilab code"
            message = render_to_string('error_email.html',
                      context)
            from_email = FROM_EMAIL
            to_email = TO_EMAIL
            cc_email = CC_EMAIL
            bcc_email = BCC_EMAIL
            # Send Emails to, cc, bcc
            msg = EmailMultiAlternatives(
                subject,
                message,
                FROM_EMAIL,
                [TO_EMAIL],
                bcc=[BCC_EMAIL],
                cc=[CC_EMAIL]
                )
            msg.content_subtype = "html"
            #msg.send()
            print (data)
        return data

    def trim(self, output):
        output = [line for line in output.split('\n') if line.strip() != '']
        output = '\n'.join(output)
        return output
